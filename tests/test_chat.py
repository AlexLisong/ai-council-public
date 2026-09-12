"""Chat API, durable history, access control, cancellation, and real SSE decoding."""

import asyncio
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from backend import auth, chat, config, db, discussion, interaction, main, providers
from model_fixtures import provider_registry


CHAT_CONFIG = {
    "default_preset": "openai",
    "chat_default": {"provider": "openai", "model": "gpt-4.1-mini"},
    "presets": {
        "openai": {
            "seats": [{"name": "A", "provider": "openai", "model": "gpt-4.1", "persona": "Compare evidence."}],
            "chairman": {"provider": "openai", "model": "gpt-4.1-mini"},
        },
    },
}


async def event(stream):
    while True:
        chunk = await anext(stream)
        if chunk.startswith("data: "):
            return json.loads(chunk[6:])


async def collect(stream):
    return [json.loads(chunk[6:]) async for chunk in stream if chunk.startswith("data: ")]


class ConversationModeMigrationTests(unittest.TestCase):
    def test_existing_sqlite_conversations_become_councils_without_rewriting_history(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(db, "DB_PATH", str(Path(folder) / "old.db")):
            with sqlite3.connect(db.DB_PATH) as conn:
                conn.executescript("""
                    CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, role TEXT, created_at TEXT);
                    CREATE TABLE conversations (id TEXT PRIMARY KEY, owner_id INTEGER, created_at TEXT, updated_at TEXT, title TEXT, messages TEXT);
                    INSERT INTO users VALUES (1, 'owner', 'unused', 'user', '2026-01-01');
                """)
                original = json.dumps([
                    {"role": "user", "content": "A saved question"},
                    {"role": "assistant", "config": {"chairman": {"provider": "anthropic", "model": "claude-old"}},
                     "final": {"response": "A historical answer"}},
                ])
                conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
                             ("old", 1, "2026-01-01", "2026-02-01", "Saved title", original))
            db.init_db()
            db.init_db()  # Idempotent on restart.
            old = db.get_conversation("old")
            self.assertEqual(old["mode"], "council")
            self.assertEqual(old["owner_id"], 1)
            self.assertEqual(old["title"], "Saved title")
            self.assertEqual(old["updated_at"], "2026-02-01")
            with db.connect() as conn:
                self.assertEqual(conn.execute("SELECT messages FROM conversations WHERE id='old'").fetchone()[0], original)
            db.create_conversation("new", 1, "chat")
            db.init_db()
            self.assertEqual(db.get_conversation("new")["mode"], "chat")
            self.assertEqual({item["id"]: item["mode"] for item in db.list_conversations(1)}, {"old": "council", "new": "chat"})
            path = Path(folder) / "legacy.json"
            path.write_text(json.dumps({"id": "legacy", "messages": [{"role": "user", "content": "JSON history"}]}))
            with patch.object(db, "DATA_DIR", folder):
                self.assertEqual(db.import_legacy_json(1), 1)
            self.assertEqual(db.get_conversation("legacy")["mode"], "council")


class ChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = copy.deepcopy(CHAT_CONFIG)
        for replacement in (
            patch.object(db, "DB_PATH", str(Path(self.temp.name) / "council.db")),
            patch.object(config, "load_council_config", return_value=self.config),
            patch.object(config, "PROVIDERS", provider_registry("openai")),
            patch.object(config, "EXTRA_MODELS", []),
            patch.object(main, "active_runs", interaction.ActiveRuns()),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db()
        self.owner = db.create_user("owner", "unused")
        self.other = db.create_user("other", "unused")
        self.admin = db.create_user("admin", "unused", role="admin")
        self.conversation = db.create_conversation("chat-test", self.owner["id"], "chat")
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.headers = {person["id"]: {"Authorization": f"Bearer {auth.issue_token(person['id'])}"} for person in (self.owner, self.other, self.admin)}
        self.calls = []

        async def model(provider, model, history):
            self.calls.append((provider, model, copy.deepcopy(history)))
            yield "Hello"
            yield ", world."

        self.title = AsyncMock(return_value="A clear title")
        for replacement in (patch.object(main, "stream_chat", model), patch.object(main, "generate_title", self.title)):
            replacement.start()
            self.addCleanup(replacement.stop)

    async def start(self, **body):
        response = await main.send_message_stream(
            self.conversation["id"], main.SendMessageRequest(content=body.pop("content", "Hello there"), **body), self.owner,
        )
        self.addAsyncCleanup(response.body_iterator.aclose)
        return response.body_iterator

    def saved(self):
        return db.get_conversation(self.conversation["id"])

    def test_create_list_get_expose_durable_mode_and_omission_keeps_council(self):
        headers = self.headers[self.owner["id"]]
        for body, expected in ((None, "council"), ({}, "council"), ({"mode": "chat"}, "chat"), ({"mode": "council"}, "council")):
            response = self.client.post("/api/conversations", headers=headers, **({"json": body} if body is not None else {}))
            self.assertEqual(response.status_code, 200)
            created = response.json()
            self.assertEqual(created["mode"], expected)
            fetched = self.client.get(f"/api/conversations/{created['id']}", headers=headers).json()
            self.assertEqual(fetched["mode"], expected)
        listed = self.client.get("/api/conversations", headers=headers).json()
        self.assertTrue(all(row["mode"] in {"council", "chat"} for row in listed))
        for body in ({"mode": "invalid"}, {"mode": None}, {"mode": 1}, {"mode": "chat", "owner_id": self.other["id"]}):
            self.assertEqual(self.client.post("/api/conversations", headers=headers, json=body).status_code, 422)

    async def test_streaming_followup_uses_roles_saves_final_and_inherits_model(self):
        events = await collect(await self.start(content="  Remember that my favorite color is blue.  ", provider="openai", model="gpt-4.1"))
        self.assertEqual([item["type"] for item in events], ["config", "chat_delta", "chat_delta", "final_complete", "title_complete", "complete"])
        self.assertEqual(events[0]["data"], {"mode": "chat", "provider": "openai", "model": "gpt-4.1", "turn_number": 1, "is_followup": False})
        self.assertEqual([item["data"]["content"] for item in events if item["type"] == "chat_delta"], ["Hello", ", world."])
        self.assertEqual(self.saved()["messages"][-1], {
            "role": "assistant", "mode": "chat", "config": events[0]["data"], "content": "Hello, world.",
            "final": events[3]["data"], "error": None, "rounds": [], "human_inputs": [], "waiting_for_input": None,
        })
        self.assertEqual(self.saved()["title"], "A clear title")
        prior = copy.deepcopy(self.saved()["messages"])
        followup = await collect(await self.start(content="What is my favorite color?"))
        self.assertEqual(self.calls[-1][:2], ("openai", "gpt-4.1"))
        self.assertEqual(self.calls[-1][2], [
            {"role": "system", "content": chat.CHAT_SYSTEM},
            {"role": "user", "content": "Remember that my favorite color is blue."},
            {"role": "assistant", "content": "Hello, world."},
            {"role": "user", "content": "What is my favorite color?"},
        ])
        self.assertEqual(self.saved()["messages"][:2], prior)
        self.assertEqual(followup[0]["data"]["turn_number"], 2)
        self.assertTrue(followup[0]["data"]["is_followup"])
        self.title.assert_awaited_once()
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_chat_default_fallback_and_explicit_model_changes(self):
        public = self.client.get("/api/config", headers=self.headers[self.owner["id"]]).json()
        self.assertEqual(public["chat_default"], CHAT_CONFIG["chat_default"])
        await collect(await self.start())
        self.assertEqual(self.calls[-1][1], "gpt-4.1-mini")
        await collect(await self.start(provider="openai", model="gpt-4.1"))
        await collect(await self.start())
        self.assertEqual(self.calls[-1][1], "gpt-4.1")
        self.config["chat_default"] = {"provider": "custom", "model": "unknown"}
        self.assertEqual(config.public_config()["chat_default"], {"provider": "openai", "model": "gpt-4.1"})
        with patch.object(config, "PROVIDERS", {}):
            self.assertIsNone(config.public_config()["chat_default"])
            before = self.saved()["messages"]
            with self.assertRaises(HTTPException) as caught:
                await self.start()
            self.assertEqual(caught.exception.status_code, 422)
            self.assertEqual(self.saved()["messages"], before)

    def test_invalid_model_pairs_and_mode_override_do_not_save_or_call(self):
        url = f"/api/conversations/{self.conversation['id']}/message/stream"
        for body in (
            {"content": " "}, {"content": "x", "provider": "openai"}, {"content": "x", "model": "gpt-4.1"},
            {"content": "x", "provider": "openai", "model": "claude-opus"},
            {"content": "x", "provider": "openai", "model": "gpt-5.1"},  # Known but not configured.
            {"content": "x", "provider": "custom", "model": "gpt-4.1"},
            {"content": "x", "mode": "council"},
        ):
            self.assertEqual(self.client.post(url, json=body, headers=self.headers[self.owner["id"]]).status_code, 422)
        self.assertEqual(self.saved()["messages"], [])
        self.assertEqual(self.saved()["mode"], "chat")
        self.assertEqual(self.calls, [])
        self.title.assert_not_awaited()

    async def test_council_message_cannot_switch_mode_with_chat_model_fields(self):
        council = db.create_conversation("council", self.owner["id"])
        with self.assertRaises(HTTPException) as caught:
            await main.send_message_stream(council["id"], main.SendMessageRequest(content="x", provider="openai", model="gpt-4.1"), self.owner)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(db.get_conversation(council["id"])["messages"], [])

    def test_chat_owner_isolation_and_admin_read_only(self):
        url = f"/api/conversations/{self.conversation['id']}"
        for person, read_status, write_status in ((self.other, 404, 404), (self.admin, 200, 403)):
            headers = self.headers[person["id"]]
            self.assertEqual(self.client.get(url, headers=headers).status_code, read_status)
            self.assertEqual(self.client.post(url + "/message/stream", json={"content": "intrude"}, headers=headers).status_code, write_status)
            self.assertEqual(self.client.post(url + "/input", json={"content": "intrude"}, headers=headers).status_code, write_status)
            self.assertEqual(self.client.delete(url, headers=headers).status_code, write_status)
        self.assertEqual(self.client.get("/api/conversations", headers=self.headers[self.other["id"]]).json(), [])
        self.assertEqual(self.client.get("/api/conversations?scope=all", headers=self.headers[self.other["id"]]).status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_context_and_turn_limits_include_full_assistant_text_before_save_or_call(self):
        prior = [{"role": "user", "content": "old"}, {"role": "assistant", "mode": "chat", "content": "x" * 100, "final": None}]
        db.save_messages(self.conversation["id"], prior)
        with patch.object(discussion, "MAX_CONTEXT_CHARS", 100):
            with self.assertRaises(HTTPException) as caught:
                await self.start()
            self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(self.saved()["messages"], prior)
        with patch.object(discussion, "MAX_HUMAN_TURNS", 1):
            with self.assertRaises(HTTPException) as caught:
                await self.start()
            self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(self.saved()["messages"], prior)
        self.assertEqual(self.calls, [])
        self.title.assert_not_awaited()

    async def test_disconnect_keeps_partial_content_closes_provider_and_releases_lease(self):
        closed = asyncio.Event()
        waiting = asyncio.Event()
        title_closed = asyncio.Event()

        async def model(*_):
            try:
                yield "Partial answer"
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        async def title(*_, **__):
            try:
                await asyncio.Event().wait()
            finally:
                title_closed.set()

        with patch.object(main, "stream_chat", model), patch.object(main, "generate_title", title):
            stream = await self.start()
            self.assertEqual((await event(stream))["type"], "config")
            self.assertEqual((await event(stream))["data"]["content"], "Partial answer")
            self.assertEqual(self.saved()["messages"][-1]["content"], "Partial answer")
            for action in (lambda: self.start(), lambda: main.delete_conversation(self.conversation["id"], self.owner),
                           lambda: main.submit_human_input(self.conversation["id"], main.HumanInputRequest(content="Wait"), self.owner)):
                with self.assertRaises(HTTPException) as caught:
                    await action()
                self.assertEqual(caught.exception.status_code, 409)
            pending = asyncio.create_task(anext(stream))
            await waiting.wait()
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        self.assertTrue(closed.is_set())
        self.assertTrue(title_closed.is_set())
        saved = self.saved()["messages"][-1]
        self.assertEqual(saved["content"], "Partial answer")
        self.assertIsNone(saved["final"])
        self.assertIn("interrupted", saved["error"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))
        await collect(await self.start(content="Please continue"))
        self.assertEqual(self.calls[-1][2][-2], {"role": "assistant", "content": "Partial answer"})

    async def test_close_immediately_after_delta_preserves_partial_and_after_final_keeps_success(self):
        stream = await self.start()
        await event(stream)
        await event(stream)
        await stream.aclose()
        self.assertEqual(self.saved()["messages"][-1]["content"], "Hello")
        self.assertIn("interrupted", self.saved()["messages"][-1]["error"])
        stream = await self.start()
        while (await event(stream))["type"] != "final_complete":
            pass
        await stream.aclose()
        self.assertEqual(self.saved()["messages"][-1]["final"]["response"], "Hello, world.")
        self.assertIsNone(self.saved()["messages"][-1]["error"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_upstream_failure_keeps_partial_sends_safe_error_and_allows_next_turn(self):
        async def failed(*_):
            yield "Some paid-for output"
            raise RuntimeError("secret upstream detail https://secret.example/?api-key=private")

        with patch.object(main, "stream_chat", failed):
            events = await collect(await self.start())
        self.assertEqual([item["type"] for item in events][-2:], ["error", "complete"])
        self.assertNotIn("secret", json.dumps(events))
        saved = self.saved()["messages"][-1]
        self.assertEqual(saved["content"], "Some paid-for output")
        self.assertNotIn("secret", saved["error"])
        self.assertIsNone(saved["final"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))
        await collect(await self.start())
        self.assertIsNotNone(self.saved()["messages"][-1]["final"])

    async def test_disconnect_before_headers_does_not_save_or_spend(self):
        response = await main.send_message_stream(self.conversation["id"], main.SendMessageRequest(content="x"), self.owner)

        async def broken_send(_):
            raise OSError("disconnected")

        async def receive():
            return {"type": "http.disconnect"}

        with self.assertRaises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, broken_send)
        self.assertEqual(self.saved()["messages"], [])
        self.assertEqual(self.calls, [])
        self.title.assert_not_awaited()
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_finished_response_bounds_title_wait_and_releases_lease_for_followup(self):
        title_closed = asyncio.Event()

        async def slow_title(*_, **__):
            try:
                await asyncio.Event().wait()
            finally:
                title_closed.set()

        prompt = "  A   useful question with enough detail to make a longer title for this test  "
        with patch.object(main, "generate_title", slow_title), patch.object(main, "TITLE_WAIT_SECONDS", 0.005):
            events = await asyncio.wait_for(collect(await self.start(content=prompt)), timeout=0.5)
        self.assertTrue(title_closed.is_set())
        self.assertEqual([item["type"] for item in events][-3:], ["final_complete", "title_complete", "complete"])
        self.assertEqual(events[-2]["data"]["title"], "A useful question with enough detail to make a ...")
        self.assertEqual(self.saved()["title"], events[-2]["data"]["title"])
        self.assertIsNone(self.saved()["messages"][-1]["error"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))
        await collect(await self.start(content="Continue after the completed answer"))
        self.assertEqual(len(self.saved()["messages"]), 4)

    async def test_title_failure_does_not_change_a_completed_response_into_an_error(self):
        with patch.object(main, "generate_title", AsyncMock(side_effect=RuntimeError("Title failed"))):
            events = await collect(await self.start(content="A useful question"))
        self.assertEqual(events[-2], {"type": "title_complete", "data": {"title": "A useful question"}})
        self.assertIsNone(self.saved()["messages"][-1]["error"])
        self.assertIsNotNone(self.saved()["messages"][-1]["final"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_restart_recovery_preserves_partial_chat_and_completed_responses(self):
        partial = {"role": "assistant", "mode": "chat", "content": "Keep partial", "final": None, "error": None, "waiting_for_input": None}
        complete = {**partial, "content": "Complete", "final": {"response": "Complete"}}
        db.save_messages(self.conversation["id"], [{"role": "user", "content": "x"}, complete, partial])
        self.assertEqual(db.recover_interrupted_runs(), 1)
        self.assertEqual(self.saved()["messages"][1], complete)
        self.assertEqual(self.saved()["messages"][2]["content"], "Keep partial")
        self.assertIn("Chat interrupted", self.saved()["messages"][2]["error"])
        self.assertEqual(db.recover_interrupted_runs(), 0)


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks, failure=None):
        self.chunks = chunks
        self.failure = failure
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.failure:
            raise self.failure

    async def aclose(self):
        self.closed = True


def packet(content=None, reason=None):
    return ("data: " + json.dumps({"choices": [{"delta": {"content": content}, "finish_reason": reason}]}) + "\n\n").encode()


class ProviderStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for replacement in (
            patch.object(config, "load_council_config", return_value=CHAT_CONFIG),
            patch.object(config, "PROVIDERS", provider_registry("openai")),
            patch.object(config, "EXTRA_MODELS", []),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    async def client(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        replacement = patch.object(providers, "_get_client", return_value=client)
        replacement.start()
        self.addCleanup(replacement.stop)
        return client

    async def test_httpx_stream_sends_roles_and_stream_flag_and_handles_split_frames(self):
        raw = b": heartbeat\n\n" + packet("Hi ") + packet("there") + b'data: {"choices":[],"usage":{}}\n\n' + packet(reason="stop") + b"data: [DONE]\n\n"
        byte_stream = ByteStream([raw[:8], raw[8:41], raw[41:87], raw[87:]])
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, stream=byte_stream, headers={"content-type": "text/event-stream"})

        await self.client(handler)
        history = [{"role": "system", "content": "helpful"}, {"role": "user", "content": "hi"}]
        result = [delta async for delta in providers.stream_chat("openai", "gpt-4.1", history)]
        self.assertEqual(result, ["Hi ", "there"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), "https://api.openai.com/v1/chat/completions")
        self.assertEqual(json.loads(requests[0].content), {"model": "gpt-4.1", "messages": history, "stream": True, "max_completion_tokens": providers.MAX_OUTPUT_TOKENS})
        self.assertTrue(byte_stream.closed)

    async def test_transient_status_retries_before_output_but_transport_failure_after_delta_never_retries(self):
        attempts = []

        def handler(request):
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(429, text="private upstream error")
            return httpx.Response(200, stream=ByteStream([packet("ok"), packet(reason="stop")]))

        await self.client(handler)
        with patch.object(providers.asyncio, "sleep", AsyncMock()) as sleep:
            self.assertEqual([delta async for delta in providers.stream_chat("openai", "gpt-4.1", [])], ["ok"])
            sleep.assert_awaited_once()
        self.assertEqual(len(attempts), 2)
        attempts.clear()
        failed = ByteStream([packet("partial")], httpx.ReadError("private key in upstream detail"))

        def failing(request):
            attempts.append(request)
            return httpx.Response(200, stream=failed)

        await self.client(failing)
        stream = providers.stream_chat("openai", "gpt-4.1", [])
        self.assertEqual(await anext(stream), "partial")
        with self.assertRaises(providers.ChatError) as caught:
            await anext(stream)
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(len(attempts), 1)
        self.assertTrue(failed.closed)

    async def test_empty_malformed_truncated_and_cutoff_streams_fail_without_success(self):
        for chunks in (
            [b"data: [DONE]\n\n"], [b"data: not-json\n\n"], [packet("partial")],
            [packet("partial"), packet(reason="length")], [packet("partial"), b"data: [DONE]"],
            [b'data: {"error":{"message":"secret provider error"}}\n\n'],
        ):
            with self.subTest(chunks=chunks):
                byte_stream = ByteStream(chunks)
                await self.client(lambda _: httpx.Response(200, stream=byte_stream))
                deltas = []
                with self.assertRaises(providers.ChatError) as caught:
                    async for delta in providers.stream_chat("openai", "gpt-4.1", []):
                        deltas.append(delta)
                self.assertNotIn("secret", str(caught.exception))
                self.assertTrue(byte_stream.closed)

    async def test_http_error_messages_are_safe_and_provider_stream_closes_on_cancel(self):
        await self.client(lambda _: httpx.Response(401, text="api key secret"))
        with self.assertRaises(providers.ChatError) as caught:
            await anext(providers.stream_chat("openai", "gpt-4.1", []))
        self.assertNotIn("secret", str(caught.exception))
        stream_data = ByteStream([packet("partial"), packet("more"), packet(reason="stop")])
        await self.client(lambda _: httpx.Response(200, stream=stream_data))
        stream = providers.stream_chat("openai", "gpt-4.1", [])
        self.assertEqual(await anext(stream), "partial")
        await stream.aclose()
        self.assertTrue(stream_data.closed)

    async def test_stop_frame_finishes_immediately_without_waiting_for_a_later_disconnect(self):
        byte_stream = ByteStream([packet("Complete answer"), packet(reason="stop")], httpx.ReadError("Later disconnect"))
        await self.client(lambda _: httpx.Response(200, stream=byte_stream))
        self.assertEqual([delta async for delta in providers.stream_chat("openai", "gpt-4.1", [])], ["Complete answer"])
        self.assertTrue(byte_stream.closed)

        for chunks in ([packet(reason="stop")], [packet("   "), packet(reason="stop")]):
            await self.client(lambda _: httpx.Response(200, stream=ByteStream(chunks)))
            with self.assertRaises(providers.ChatError) as caught:
                _ = [delta async for delta in providers.stream_chat("openai", "gpt-4.1", [])]
            self.assertIn("empty response", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
