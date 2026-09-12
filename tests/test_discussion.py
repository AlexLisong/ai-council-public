"""Follow-up and live-input regressions with deterministic local model doubles."""

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from backend import auth, config, db, debate, discussion, interaction, main
from model_fixtures import provider_registry


PRESETS = {
    "default_preset": "test-panel",
    "presets": {
        "test-panel": {
            "seats": [
                {"name": "Skeptic", "provider": "openai", "model": "gpt-4.1", "persona": "Check evidence."},
                {"name": "Builder", "provider": "openai", "model": "gpt-4.1-mini", "persona": "Check implementation."},
            ],
            "chairman": {"provider": "openai", "model": "gpt-4.1"},
        },
    },
}


async def next_event(stream):
    while True:
        chunk = await anext(stream)
        if chunk.startswith("data: "):
            return json.loads(chunk[6:])


async def all_events(stream):
    result = []
    async for chunk in stream:
        if chunk.startswith("data: "):
            result.append(json.loads(chunk[6:]))
    return result


class DiscussionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for replacement in (
            patch.object(db, "DB_PATH", str(Path(self.temp.name) / "council.db")),
            patch.object(main, "active_runs", interaction.ActiveRuns()),
            patch.object(debate, "load_council_config", return_value=PRESETS),
            patch.object(config, "load_council_config", return_value=PRESETS),
            patch.object(config, "PROVIDERS", provider_registry("openai")),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db()
        self.owner = db.create_user("owner", "unused")
        self.conversation = db.create_conversation("discussion-test", self.owner["id"])
        self.title = AsyncMock(return_value="Stable discussion title")
        title_patch = patch.object(main, "generate_title", self.title)
        title_patch.start()
        self.addCleanup(title_patch.stop)
        self.calls = []
        self.chair_calls = []

        async def seats(calls):
            self.calls.extend(calls)
            return [f"Answer by {call[1]}\nPOSITION SUMMARY: Keep evidence explicit.\nVERDICT: CONVERGED\nDISAGREEMENTS: none" for call in calls]

        async def chairman(*args):
            self.chair_calls.append(args)
            return "Synthesis considers the human's evidence."

        for replacement in (patch.object(debate, "chat_many", seats), patch.object(debate, "chat", chairman)):
            replacement.start()
            self.addCleanup(replacement.stop)

    async def start(self, **options):
        request = main.SendMessageRequest(content=options.pop("content", "Where should we build the warehouse?"), **options)
        response = await main.send_message_stream(self.conversation["id"], request, self.owner)
        self.addAsyncCleanup(response.body_iterator.aclose)
        return response

    async def waiting_stream(self, **options):
        response = await self.start(max_rounds=options.pop("max_rounds", 2), **options)
        stream = response.body_iterator
        while True:
            event = await next_event(stream)
            if event["type"] == "awaiting_input":
                return stream, event

    def saved_assistant(self):
        return db.get_conversation(self.conversation["id"])["messages"][-1]

    async def test_followup_reuses_settings_and_keeps_full_context_and_prior_turns(self):
        old = [
            {"role": "user", "content": "Original warehouse question"},
            {
                "role": "assistant",
                "config": {"preset": "test-panel", "max_rounds": 1, "consensus": "majority", "pause_for_input": False},
                "rounds": [
                    {"round": 0, "entries": [{"seat_id": "seat0", "response": "Position about river flooding"}, {"seat_id": "seat1", "response": "Position about staffing costs"}]},
                    {"round": 1, "entries": [{"seat_id": "seat0", "response": "Updated floodplain evidence"}]},
                ],
                "final": {"response": "Earlier synthesis: compare the two locations"},
                "human_inputs": [{"after_round": 0, "content": "My earlier budget is $20m", "created_at": "2026-01-01T00:00:00+00:00"}],
            },
        ]
        original = copy.deepcopy(old)
        db.save_messages(self.conversation["id"], old)
        db.update_title(self.conversation["id"], "Existing title")
        response = await self.start(content="  The warehouse must be flood-safe  ")
        events = await all_events(response.body_iterator)
        self.assertNotIn("awaiting_input", [event["type"] for event in events])
        self.title.assert_not_awaited()
        saved = db.get_conversation(self.conversation["id"])
        self.assertEqual(saved["title"], "Existing title")
        self.assertEqual(saved["messages"][:2], original)
        self.assertEqual(saved["messages"][2], {"role": "user", "content": "The warehouse must be flood-safe"})
        config = saved["messages"][3]["config"]
        for key, value in old[1]["config"].items():
            self.assertEqual(config[key], value)
        self.assertEqual(config["turn_number"], 2)
        self.assertTrue(config["is_followup"])
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(len(self.chair_calls), 1)
        for call in self.calls + self.chair_calls:
            for text in (
                "Original warehouse question", "Updated floodplain evidence", "Position about staffing costs",
                "Earlier synthesis: compare the two locations", "My earlier budget is $20m", "The warehouse must be flood-safe",
            ):
                self.assertIn(text, call[3])
            self.assertIn("explicitly assess the latest human thought", call[2])
            self.assertIn("unverified claims", call[2])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_live_thought_is_saved_before_resume_and_reaches_every_later_model(self):
        stream, event = await self.waiting_stream()
        self.assertEqual(event["data"]["after_round"], 0)
        self.assertIn("+00:00", event["data"]["deadline"])
        self.assertEqual(self.saved_assistant()["waiting_for_input"], event["data"])
        self.assertEqual(len(self.calls), 2)
        result = await main.submit_human_input(
            self.conversation["id"], main.HumanInputRequest(content="I measured a 2m flood at site A"), self.owner,
        )
        self.assertEqual(result["reason"], "input")
        self.assertEqual(self.saved_assistant()["human_inputs"], [result["input"]])
        self.assertIsNone(self.saved_assistant()["waiting_for_input"])
        with self.assertRaises(HTTPException) as caught:
            await main.submit_human_input(self.conversation["id"], main.HumanInputRequest(content="duplicate"), self.owner)
        self.assertEqual(caught.exception.status_code, 409)
        tail = await all_events(stream)
        self.assertEqual(tail[0], {"type": "input_received", "data": result["input"]})
        self.assertEqual(tail[1]["data"]["reason"], "input")
        self.assertNotIn("awaiting_input", [item["type"] for item in tail])  # Quorum ends round 1.
        for call in self.calls[2:] + self.chair_calls:
            self.assertIn("I measured a 2m flood at site A", call[3])
        self.assertIsNotNone(self.saved_assistant()["final"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_timeout_automatically_resumes_and_skip_creates_no_human_thought(self):
        with patch.object(interaction, "INPUT_WAIT_SECONDS", 0.005):
            response = await self.start(max_rounds=1)
            events = await all_events(response.body_iterator)
        resumed = [event for event in events if event["type"] == "round_resumed"]
        self.assertEqual([event["data"]["reason"] for event in resumed], ["timeout"])
        self.assertEqual(self.saved_assistant()["human_inputs"], [])
        self.assertIsNone(self.saved_assistant()["waiting_for_input"])
        stream, _ = await self.waiting_stream(content="Continue with a fresh comparison", max_rounds=1)
        result = await main.submit_human_input(self.conversation["id"], main.HumanInputRequest(skip=True), self.owner)
        self.assertIsNone(result["input"])
        events = await all_events(stream)
        self.assertNotIn("input_received", [event["type"] for event in events])
        self.assertEqual(next(event["data"]["reason"] for event in events if event["type"] == "round_resumed"), "skip")
        self.assertEqual(self.saved_assistant()["human_inputs"], [])

    async def test_round_cap_has_only_between_round_waits(self):
        async def open_positions(calls):
            return ["Still uncertain.\nPOSITION SUMMARY: Need more evidence.\nVERDICT: OPEN\nDISAGREEMENTS: flood risk" for _ in calls]

        with patch.object(debate, "chat_many", open_positions), patch.object(interaction, "INPUT_WAIT_SECONDS", 0.001):
            response = await self.start(max_rounds=2)
            events = await all_events(response.body_iterator)
        waits = [event["data"]["after_round"] for event in events if event["type"] == "awaiting_input"]
        self.assertEqual(waits, [0, 1])
        self.assertFalse(self.saved_assistant()["final"]["converged"])
        self.assertEqual(self.saved_assistant()["final"]["rounds_run"], 2)
        self.assertIsNone(self.saved_assistant()["waiting_for_input"])

    async def test_accepted_thought_survives_disconnect_and_enters_the_next_followup(self):
        stream, _ = await self.waiting_stream()
        await main.submit_human_input(
            self.conversation["id"], main.HumanInputRequest(content="Do not lose my measured flood level"), self.owner,
        )
        await stream.aclose()  # Disconnect before the engine resumes from the waiting event.
        self.assertEqual(self.saved_assistant()["human_inputs"][0]["content"], "Do not lose my measured flood level")
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))
        self.calls.clear()
        response = await self.start(content="Continue using my measurement", max_rounds=0)
        await all_events(response.body_iterator)
        for call in self.calls + self.chair_calls:
            self.assertIn("Do not lose my measured flood level", call[3])

    async def test_active_stream_blocks_duplicate_delete_and_unauthorized_input_then_cleans_up(self):
        stream, _ = await self.waiting_stream()
        client = TestClient(main.app)
        self.addCleanup(client.close)
        for action in (
            lambda: main.send_message_stream(self.conversation["id"], main.SendMessageRequest(content="duplicate"), self.owner),
            lambda: main.delete_conversation(self.conversation["id"], self.owner),
        ):
            with self.assertRaises(HTTPException) as caught:
                await action()
            self.assertEqual(caught.exception.status_code, 409)
        for role, expected in (("admin", 403), ("user", 404)):
            user = db.create_user("other-" + role, "unused", role=role)
            token = auth.issue_token(user["id"])
            result = client.post(
                f"/api/conversations/{self.conversation['id']}/input",
                headers={"Authorization": f"Bearer {token}"}, json={"content": "intrusion"},
            )
            self.assertEqual(result.status_code, expected)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        saved = self.saved_assistant()
        self.assertIsNone(saved["waiting_for_input"])
        self.assertEqual(len(saved["rounds"]), 1)
        self.assertIn("interrupted", saved["error"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))
        response = await self.start(content="Try again", max_rounds=0)
        events = await all_events(response.body_iterator)
        self.assertNotIn("awaiting_input", [event["type"] for event in events])

    async def test_invalid_requests_and_history_limits_do_not_append_or_spend(self):
        token = auth.issue_token(self.owner["id"])
        client = TestClient(main.app)
        self.addCleanup(client.close)
        url = f"/api/conversations/{self.conversation['id']}/message/stream"
        for body in (
            {"content": "  \n  "}, {"content": "test", "preset": "missing"},
            {"content": "test", "consensus": "Infinity"}, {"content": "test", "consensus": "2/1"},
            {"content": "test", "max_rounds": -1}, {"content": "test", "max_rounds": True},
        ):
            response = client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(db.get_conversation(self.conversation["id"])["messages"], [])
        db.save_messages(self.conversation["id"], [{"role": "user", "content": "old question"}])
        with patch.object(discussion, "MAX_CONTEXT_CHARS", 10):
            with self.assertRaises(HTTPException) as caught:
                await self.start(content="new thought")
            self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(len(db.get_conversation(self.conversation["id"])["messages"]), 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.chair_calls, [])
        self.title.assert_not_awaited()

    async def test_rejected_live_input_preserves_wait_and_model_failure_releases_run(self):
        stream, _ = await self.waiting_stream()
        with patch.object(discussion, "MAX_CONTEXT_CHARS", 10):
            with self.assertRaises(HTTPException) as caught:
                await main.submit_human_input(self.conversation["id"], main.HumanInputRequest(content="oversized thought"), self.owner)
            self.assertEqual(caught.exception.status_code, 413)
        self.assertIsNotNone(self.saved_assistant()["waiting_for_input"])
        self.assertEqual(self.saved_assistant()["human_inputs"], [])
        await main.submit_human_input(self.conversation["id"], main.HumanInputRequest(skip=True), self.owner)
        with patch.object(debate, "chat_many", AsyncMock(side_effect=RuntimeError("model test failure"))):
            events = await all_events(stream)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("model test failure", self.saved_assistant()["error"])
        self.assertIsNone(self.saved_assistant()["waiting_for_input"])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_response_failure_before_stream_start_releases_lease(self):
        response = await self.start(max_rounds=0)

        async def broken_send(_):
            raise OSError("client disconnected before headers")

        async def receive():
            return {"type": "http.disconnect"}

        with self.assertRaises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, broken_send)
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))
        self.assertEqual(db.get_conversation(self.conversation["id"])["messages"], [])

    async def test_startup_recovers_interrupted_turn_without_losing_thoughts_rounds_or_finals(self):
        completed = {
            "role": "assistant", "rounds": [{"round": 0, "entries": []}],
            "final": {"response": "Completed synthesis"}, "error": None, "waiting_for_input": None,
        }
        interrupted = {
            "role": "assistant", "rounds": [{"round": 0, "entries": [{"seat_id": "seat0", "response": "Paid-for position"}]}],
            "final": None, "error": None,
            "human_inputs": [{"after_round": 0, "content": "A saved human measurement", "created_at": "2026-01-01T00:00:00+00:00"}],
            "waiting_for_input": {"after_round": 0, "deadline": "2099-01-01T00:00:00+00:00"},
        }
        messages = [
            {"role": "user", "content": "Original question"}, copy.deepcopy(completed),
            {"role": "user", "content": "Follow-up question"}, copy.deepcopy(interrupted),
        ]
        db.save_messages(self.conversation["id"], messages)
        db.update_title(self.conversation["id"], "Keep this title")
        with patch.object(auth, "bootstrap_admin"), patch.object(main, "close_client", AsyncMock()):
            async with main.lifespan(main.app):
                saved = db.get_conversation(self.conversation["id"])
        self.assertEqual(saved["title"], "Keep this title")
        self.assertEqual(saved["messages"][1], completed)
        recovered = saved["messages"][-1]
        self.assertIsNone(recovered["waiting_for_input"])
        self.assertIn("interrupted", recovered["error"])
        self.assertEqual(recovered["human_inputs"], interrupted["human_inputs"])
        self.assertEqual(recovered["rounds"], interrupted["rounds"])
        self.assertEqual(db.recover_interrupted_runs(), 0)

    async def test_get_normalizes_orphaned_wait_but_preserves_a_live_wait(self):
        db.save_messages(self.conversation["id"], [
            {"role": "user", "content": "Original question"},
            {"role": "assistant", "rounds": [], "final": None, "error": None,
             "waiting_for_input": {"after_round": 0, "deadline": "2099-01-01T00:00:00+00:00"}},
        ])
        snapshot = await main.get_conversation(self.conversation["id"], self.owner)
        self.assertFalse(snapshot["is_running"])
        self.assertIsNone(snapshot["messages"][-1]["waiting_for_input"])
        self.assertIn("interrupted", self.saved_assistant()["error"])
        self.assertIsNone(self.saved_assistant()["waiting_for_input"])
        stream, event = await self.waiting_stream(content="Continue the interrupted discussion")
        snapshot = await main.get_conversation(self.conversation["id"], self.owner)
        self.assertTrue(snapshot["is_running"])
        self.assertEqual(snapshot["messages"][-1]["waiting_for_input"], event["data"])
        self.assertIsNone(snapshot["messages"][-1]["error"])
        await stream.aclose()
        self.assertFalse((await main.get_conversation(self.conversation["id"], self.owner))["is_running"])


if __name__ == "__main__":
    unittest.main()
