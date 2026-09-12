"""Hosting regressions; no network requests to model providers are made."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import auth, config, db, main, throttle
from backend.streaming import with_heartbeats
from backend.throttle import SlidingWindowLimiter
from model_fixtures import provider_registry


class TemporaryDatabase:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(db, "DB_PATH", str(Path(self.temp.name) / "council.db"))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()


class AccessTests(TemporaryDatabase, unittest.TestCase):
    def test_admin_view_is_read_only_and_other_users_cannot_access(self):
        admin = db.create_user("admin", "unused", role="admin")
        owner = db.create_user("owner", "unused")
        stranger = db.create_user("stranger", "unused")
        conversation = db.create_conversation("owner-debate", owner["id"])
        client = TestClient(main.app)
        self.addCleanup(client.close)
        url = f"/api/conversations/{conversation['id']}"

        for user, expected in ((admin, 403), (stranger, 404)):
            headers = {"Authorization": f"Bearer {auth.issue_token(user['id'])}"}
            self.assertEqual(client.get(url, headers=headers).status_code, 200 if user == admin else 404)
            self.assertEqual(client.delete(url, headers=headers).status_code, expected)
            response = client.post(url + "/message/stream", headers=headers, json={"content": "test"})
            self.assertEqual(response.status_code, expected)
            self.assertIsNotNone(db.get_conversation(conversation["id"]))

        owner_headers = {"Authorization": f"Bearer {auth.issue_token(owner['id'])}"}
        self.assertEqual(client.delete(url, headers=owner_headers).status_code, 204)
        self.assertIsNone(db.get_conversation(conversation["id"]))

    def test_delete_journal_mode_survives_reopening_database(self):
        with patch.object(db, "SQLITE_JOURNAL_MODE", "DELETE"):
            db.init_db()
        with db.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")


class ThrottleTests(TemporaryDatabase, unittest.TestCase):
    def test_login_account_limit_normalizes_name_and_ignores_forwarded_headers(self):
        account_limit = SlidingWindowLimiter(limit=2, window=60)
        client = TestClient(main.app)
        self.addCleanup(client.close)
        with (
            patch.object(throttle, "login_global", SlidingWindowLimiter(100, 60)),
            patch.object(throttle, "login_account", account_limit),
        ):
            for username, forwarded in (("Nobody", "1.1.1.1"), (" nobody ", "2.2.2.2")):
                response = client.post(
                    "/api/auth/login", json={"username": username, "password": "wrong"},
                    headers={"X-Forwarded-For": forwarded},
                )
                self.assertEqual(response.status_code, 401)
            response = client.post(
                "/api/auth/login", json={"username": "NOBODY", "password": "wrong"},
                headers={"X-Forwarded-For": "3.3.3.3"},
            )
            self.assertEqual(response.status_code, 429)
            self.assertGreater(int(response.headers["Retry-After"]), 0)

    def test_global_login_and_registration_limits_cannot_be_evaded_with_new_names(self):
        client = TestClient(main.app)
        self.addCleanup(client.close)
        with (
            patch.object(throttle, "login_global", SlidingWindowLimiter(1, 60)),
            patch.object(throttle, "login_account", SlidingWindowLimiter(10, 60, max_keys=10)),
            patch.object(throttle, "registration", SlidingWindowLimiter(1, 60)),
            patch.object(main, "ALLOW_SIGNUP", True),
        ):
            for route, first_status in (("login", 401), ("register", 400)):
                url = f"/api/auth/{route}"
                self.assertEqual(client.post(url, json={"username": "one", "password": "short"}).status_code, first_status)
                response = client.post(url, json={"username": "two", "password": "short"})
                self.assertEqual(response.status_code, 429)
                self.assertIn("Retry-After", response.headers)

    def test_full_limiter_does_not_evict_active_keys_and_recovers_after_window(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(1, 60, max_keys=2, clock=lambda: now[0])
        limiter.check("a")
        limiter.check("b")
        for key in ("c", "a"):
            with self.assertRaises(HTTPException) as caught:
                limiter.check(key)
            self.assertEqual(caught.exception.status_code, 429)
            self.assertEqual(caught.exception.headers["Retry-After"], "60")
        self.assertEqual(len(limiter._buckets), 2)
        now[0] = 60.0
        limiter.check("c")
        self.assertEqual(list(limiter._buckets), ["c"])


class StaticHostingTests(unittest.TestCase):
    def test_static_root_assets_and_api_routes_remain_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "index.html").write_text("<html>AI Council</html>")
            (directory / "app.js").write_text("console.log('app')")
            (directory / "api").mkdir()
            (directory / "api" / "fake.html").write_text("must not be served")
            application = FastAPI()
            application.add_api_route("/api/health", main.health)
            main.mount_frontend(application, directory)
            with TestClient(application) as client:
                root = client.get("/")
                self.assertEqual(root.status_code, 200)
                self.assertIn("text/html", root.headers["content-type"])
                self.assertIn("AI Council", root.text)
                self.assertEqual(client.get("/app.js").status_code, 200)
                self.assertEqual(client.get("/api/health").json()["status"], "ok")
                self.assertEqual(client.get("/api/missing").status_code, 404)
                self.assertEqual(client.get("/api/fake.html").status_code, 404)
                self.assertEqual(client.get("/.env").status_code, 404)

    def test_development_root_keeps_health_when_frontend_is_unbuilt(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = FastAPI()
            application.add_api_route("/api/health", main.health)
            main.mount_frontend(application, Path(temporary))
            with TestClient(application) as client:
                self.assertEqual(client.get("/").json(), client.get("/api/health").json())

    def test_only_known_spa_routes_fall_back_and_private_or_missing_assets_stay_404(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "index.html").write_text("<html>AI Council route shell</html>")
            (directory / ".env").write_text("This must remain private even if accidentally present in a build.")
            (directory / "assets").mkdir()
            (directory / "assets" / "app.js").write_text("console.log('app')")
            application = FastAPI()
            main.mount_frontend(application, directory)
            identifier = str(uuid4())
            with TestClient(application) as client:
                for route in (
                    "/login", "/debates", f"/debates/{identifier}", "/panels", "/panels/new",
                    f"/panels/{identifier}", f"/panels/{identifier}?seat=chairman", "/panels/new/?seat=seat0",
                ):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200, route)
                    self.assertIn("AI Council route shell", response.text)
                    self.assertIn("text/html", response.headers["content-type"])
                for route in (
                    "/api/unknown", "/api", "/assets/missing.js", "/.env", "/backend/main.py",
                    "/council.config.json", "/unknown", "/panels/not-a-uuid", f"/panels/{identifier}/extra",
                ):
                    self.assertEqual(client.get(route).status_code, 404, route)
                self.assertEqual(client.get("/assets/app.js").text, "console.log('app')")


class StreamingTests(TemporaryDatabase, unittest.IsolatedAsyncioTestCase):
    async def test_heartbeats_do_not_cancel_or_restart_pending_event(self):
        ready = asyncio.Event()
        closed = asyncio.Event()
        cancelled = []

        async def source():
            try:
                yield "first"
                await ready.wait()
                yield "last"
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            finally:
                closed.set()

        stream = with_heartbeats(source(), interval=0.001)
        self.assertEqual(await anext(stream), "first")
        self.assertEqual(await anext(stream), ": heartbeat\n\n")
        self.assertEqual(await anext(stream), ": heartbeat\n\n")
        self.assertEqual(cancelled, [])
        ready.set()
        self.assertEqual(await anext(stream), "last")
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)
        self.assertTrue(closed.is_set())

    async def test_cancellation_closes_model_and_title_and_preserves_saved_round(self):
        owner = db.create_user("owner", "unused")
        conversation = db.create_conversation("stream-debate", owner["id"])
        waiting = asyncio.Event()
        debate_closed = asyncio.Event()
        title_closed = asyncio.Event()
        completed_round = {"round": 0, "entries": [{"seat_id": "seat0", "response": "Saved answer"}]}

        async def debate(*_, **__):
            try:
                yield {"type": "round_complete", "data": completed_round}
                waiting.set()
                await asyncio.Event().wait()
            finally:
                debate_closed.set()

        async def title(*_, **__):
            try:
                await asyncio.Event().wait()
            finally:
                title_closed.set()

        with (
            patch.object(main, "run_debate", debate), patch.object(main, "generate_title", title),
            patch.object(config, "PROVIDERS", provider_registry("foundry-openai")),
        ):
            response = await main.send_message_stream(conversation["id"], main.SendMessageRequest(content="test"), owner)
            stream = response.body_iterator
            self.addAsyncCleanup(stream.aclose)
            self.assertIn("round_complete", await anext(stream))
            self.assertEqual(db.get_conversation(conversation["id"])["messages"][1]["rounds"], [completed_round])
            pending = asyncio.create_task(anext(stream))
            await waiting.wait()
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertTrue(debate_closed.is_set())
            self.assertTrue(title_closed.is_set())
            saved = db.get_conversation(conversation["id"])["messages"][1]
            self.assertEqual(saved["rounds"], [completed_round])
            self.assertIn("interrupted", saved["error"])

    async def test_closing_after_heartbeat_cleans_up_pending_source(self):
        closed = asyncio.Event()

        async def source():
            try:
                await asyncio.Event().wait()
                yield "never"
            finally:
                closed.set()

        stream = with_heartbeats(source(), interval=0.001)
        self.assertEqual(await anext(stream), ": heartbeat\n\n")
        await stream.aclose()
        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
