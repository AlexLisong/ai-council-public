"""Personal panel API and model-call contracts, using temporary SQLite and model doubles."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth, config, db, debate, interaction, main
from test_avatars import PNG
from model_fixtures import provider_registry


COUNCIL = {
    "default_preset": "built-in",
    "presets": {
        "built-in": {
            "title": "Shared template",
            "seats": [
                {"name": "Template A", "provider": "openai", "model": "gpt-4.1", "persona": "Test evidence."},
                {"name": "Template B", "provider": "openai", "model": "gpt-4.1-mini", "persona": "Test implementation."},
            ],
            "chairman": {"provider": "openai", "model": "gpt-4.1-mini"},
        },
        "unavailable": {
            "seats": [{"name": "Offline", "provider": "offline", "model": "other-model", "persona": "Not configured here."}],
            "chairman": {"provider": "offline", "model": "other-model"},
        },
    },
}


def panel_definition(version="original"):
    return {
        "title": f"My {version} panel",
        "seats": [
            {"name": f"Ada {version}", "provider": "openai", "model": "gpt-4.1", "persona": f"Use the {version} statistics perspective.", "avatar": None},
            {"name": f"Grace {version}", "provider": "openai", "model": "gpt-4.1-mini", "persona": f"Use the {version} engineering perspective.", "avatar": None},
        ],
        "chairman": {"name": f"Chair {version}", "provider": "openai", "model": "gpt-4.1-mini", "persona": f"Emphasize {version} trade-offs.", "avatar": None},
    }


async def collect(stream):
    return [json.loads(chunk[6:]) async for chunk in stream if chunk.startswith("data: ")]


class PersonalPanelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for replacement in (
            patch.object(db, "DB_PATH", str(Path(self.temp.name) / "council.db")),
            patch.object(main, "active_runs", interaction.ActiveRuns()),
            patch.object(config, "load_council_config", return_value=COUNCIL),
            patch.object(debate, "load_council_config", return_value=COUNCIL),
            patch.object(config, "PROVIDERS", provider_registry("openai")),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db()
        self.owner = db.create_user("owner", "unused")
        self.other = db.create_user("other", "unused")
        self.admin = db.create_user("admin", "unused", role="admin")
        self.conversation = db.create_conversation("personal-panel-conversation", self.owner["id"])
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.headers = {user["id"]: {"Authorization": f"Bearer {auth.issue_token(user['id'])}"} for user in (self.owner, self.other, self.admin)}
        self.seat_calls = []
        self.chair_calls = []
        self.title_calls = []

        async def seats(calls):
            self.seat_calls.extend(calls)
            return ["A position.\nPOSITION SUMMARY: Compare evidence.\nVERDICT: CONVERGED\nDISAGREEMENTS: none" for _ in calls]

        async def chat(*args, **kwargs):
            if args[2] == debate.TITLE_SYSTEM:
                self.title_calls.append(args)
                return "The original conversation title"
            self.chair_calls.append(args)
            return "A synthesis based on the selected panel."

        for replacement in (patch.object(debate, "chat_many", seats), patch.object(debate, "chat", chat)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def save_panel(self, definition=None, user=None):
        user = user or self.owner
        response = self.client.post("/api/panels", json=definition or panel_definition(), headers=self.headers[user["id"]])
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def start(self, **settings):
        response = await main.send_message_stream(
            self.conversation["id"], main.SendMessageRequest(content="Please assess these alternatives", **settings), self.owner,
        )
        self.addAsyncCleanup(response.body_iterator.aclose)
        return response.body_iterator

    def saved(self):
        return db.get_conversation(self.conversation["id"])

    async def test_saved_panels_survive_reopening_and_are_private_in_config_and_updates(self):
        template_before = copy.deepcopy(COUNCIL)
        personal = self.save_panel()
        self.assertEqual(personal["key"], f"personal:{personal['id']}")
        self.assertTrue(personal["is_personal"])
        self.assertTrue(personal["available"])
        self.assertEqual(personal["missing_providers"], [])
        self.assertEqual(self.client.get(f"/api/panels/{personal['id']}", headers=self.headers[self.owner["id"]]).json(), personal)
        db.init_db()  # Reopening applies the idempotent schema without losing the saved panel.
        owner_config = self.client.get("/api/config", headers=self.headers[self.owner["id"]]).json()
        self.assertIn(personal, owner_config["presets"])
        self.assertEqual(owner_config["model_options"], [{"provider": "openai", "model": "gpt-4.1"}, {"provider": "openai", "model": "gpt-4.1-mini"}])
        self.assertEqual(owner_config["presets"][0]["chairman"]["name"], "Chairman")
        for user in (self.other, self.admin):
            configuration = self.client.get("/api/config", headers=self.headers[user["id"]]).json()
            self.assertNotIn(personal["key"], [preset["key"] for preset in configuration["presets"]])
            response = self.client.put(f"/api/panels/{personal['id']}", json=panel_definition("intruder"), headers=self.headers[user["id"]])
            self.assertEqual(response.status_code, 404)
            self.assertEqual(self.client.get(f"/api/panels/{personal['id']}", headers=self.headers[user["id"]]).status_code, 404)
        self.assertEqual(self.client.get(f"/api/panels/{uuid4()}", headers=self.headers[self.owner["id"]]).status_code, 404)
        changed = self.client.put(f"/api/panels/{personal['id']}", json=panel_definition("updated"), headers=self.headers[self.owner["id"]])
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["title"], "My updated panel")
        self.assertEqual(db.get_panel(personal["id"], self.owner["id"])["definition"], panel_definition("updated"))
        self.assertEqual(COUNCIL, template_before)
        self.assertEqual(self.seat_calls + self.chair_calls + self.title_calls, [])

    async def test_invalid_panels_are_rejected_and_optional_chairman_guidance_is_supported(self):
        invalid = []
        for path, value in (
            (("title",), "  "), (("title",), "t" * 101),
            (("seats",), []), (("seats",), [panel_definition()["seats"][0]] * 9),
            (("seats", 0, "name"), " "), (("seats", 0, "name"), "n" * 81),
            (("seats", 0, "persona"), "\n "), (("seats", 0, "persona"), "p" * 4001),
            (("seats", 0, "model"), "invented-model"), (("seats", 0, "provider"), "invented-provider"),
            (("chairman", "name"), "\n"), (("chairman", "persona"), "p" * 4001),
            (("chairman", "provider"), "offline"),
        ):
            body = panel_definition()
            target = body
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = value
            invalid.append(body)
        invalid.append({**panel_definition(), "owner_id": self.other["id"]})
        without_chairman = panel_definition()
        without_chairman.pop("chairman")
        invalid.append(without_chairman)
        for body in invalid:
            response = self.client.post("/api/panels", json=body, headers=self.headers[self.owner["id"]])
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(db.list_panels(self.owner["id"]), [])
        body = panel_definition()
        del body["chairman"]["persona"]
        self.assertEqual(self.save_panel(body)["chairman"]["persona"], "")
        self.assertEqual(self.seat_calls + self.chair_calls + self.title_calls, [])

    async def test_foreign_missing_and_unavailable_panels_fail_before_any_model_call(self):
        foreign = self.save_panel(user=self.other)
        for key in (foreign["key"], f"personal:{uuid4()}", "personal:not-a-uuid"):
            with self.assertRaises(HTTPException) as caught:
                await self.start(preset=key, max_rounds=0)
            self.assertEqual(caught.exception.status_code, 404)
        own = self.save_panel()
        with patch.object(config, "PROVIDERS", {}):
            configuration = self.client.get("/api/config", headers=self.headers[self.owner["id"]]).json()
            personal = next(preset for preset in configuration["presets"] if preset["key"] == own["key"])
            self.assertFalse(personal["available"])
            self.assertEqual(configuration["model_options"], [])
            with self.assertRaises(HTTPException) as caught:
                await self.start(preset=own["key"], max_rounds=0)
            self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.saved()["messages"], [])
        self.assertEqual(self.seat_calls + self.chair_calls + self.title_calls, [])
        self.assertIsNone(main.active_runs.get(self.conversation["id"]))

    async def test_custom_prompts_titles_and_snapshot_inheritance_use_the_selected_version(self):
        personal = self.save_panel()
        await collect(await self.start(preset=personal["key"], max_rounds=0, pause_for_input=False))
        original_messages = copy.deepcopy(self.saved()["messages"])
        first_config = original_messages[-1]["config"]
        self.assertEqual(self.title_calls[0][:2], ("openai", "gpt-4.1-mini"))
        self.assertEqual(original_messages[-1]["final"]["chairman_name"], "Chair original")
        for call, member in zip(self.seat_calls, panel_definition()["seats"]):
            self.assertIn(member["name"], call[2])
            self.assertIn(member["persona"], call[2])
        self.assertIn("Chair original", self.chair_calls[0][2])
        self.assertIn("Emphasize original trade-offs.", self.chair_calls[0][2])
        self.assertIn(debate.CHAIRMAN_SYSTEM, self.chair_calls[0][2])
        revised = panel_definition("revised")
        revised["chairman"]["model"] = "gpt-4.1"
        self.client.put(f"/api/panels/{personal['id']}", json=revised, headers=self.headers[self.owner["id"]])
        for settings in ({"preset": personal["key"]}, {}):
            await collect(await self.start(**settings))
            current = self.saved()["messages"][-1]["config"]
            self.assertEqual(current["seats"], first_config["seats"])
            self.assertEqual(current["chairman"], first_config["chairman"])
        await collect(await self.start(preset=personal["key"], use_latest_panel=True))
        latest = self.saved()
        self.assertEqual(latest["messages"][:2], original_messages)
        self.assertEqual(latest["messages"][-1]["config"]["chairman"], revised["chairman"])
        self.assertEqual(latest["messages"][-1]["final"]["chairman_name"], "Chair revised")
        self.assertEqual(self.chair_calls[-1][:2], ("openai", "gpt-4.1"))
        self.assertEqual(len(self.title_calls), 1)
        self.assertEqual(latest["title"], "The original conversation title")
        other_panel = self.save_panel(panel_definition("different"))
        await collect(await self.start(preset=other_panel["key"]))
        self.assertEqual(self.saved()["messages"][-1]["config"]["seats"][0]["name"], "Ada different")

    async def test_editing_a_saved_panel_does_not_change_an_active_round_or_chairman(self):
        personal = self.save_panel()
        stream = await self.start(preset=personal["key"], max_rounds=1, pause_for_input=True)
        while True:
            chunk = await anext(stream)
            if chunk.startswith("data: ") and json.loads(chunk[6:])["type"] == "awaiting_input":
                break
        response = self.client.put(f"/api/panels/{personal['id']}", json=panel_definition("edited live"), headers=self.headers[self.owner["id"]])
        self.assertEqual(response.status_code, 200)
        await main.submit_human_input(self.conversation["id"], main.HumanInputRequest(skip=True), self.owner)
        await collect(stream)
        self.assertEqual(len(self.seat_calls), 4)
        for call in self.seat_calls:
            self.assertIn("original", call[2])
            self.assertNotIn("edited live", call[2])
        self.assertIn("Chair original", self.chair_calls[-1][2])
        self.assertEqual(self.saved()["messages"][-1]["config"]["seats"][0]["name"], "Ada original")

    async def test_resizing_panel_changes_only_explicit_new_snapshots_and_keeps_chairman_required(self):
        personal = self.save_panel()
        await collect(await self.start(preset=personal["key"], max_rounds=0, pause_for_input=False))
        original_messages = copy.deepcopy(self.saved()["messages"])
        enlarged = panel_definition("eight seats")
        enlarged["seats"] = [
            {**enlarged["seats"][index % 2], "name": f"Member {index + 1}"}
            for index in range(8)
        ]
        response = self.client.put(f"/api/panels/{personal['id']}", json=enlarged, headers=self.headers[self.owner["id"]])
        self.assertEqual(response.status_code, 200)
        await collect(await self.start(preset=personal["key"]))
        self.assertEqual(len(self.saved()["messages"][-1]["config"]["seats"]), 2)
        await collect(await self.start(preset=personal["key"], use_latest_panel=True))
        expanded_config = self.saved()["messages"][-1]["config"]
        self.assertEqual(len(expanded_config["seats"]), 8)
        self.assertEqual(expanded_config["quorum"], 8)
        self.assertEqual(expanded_config["chairman"], enlarged["chairman"])
        smaller = {**enlarged, "seats": enlarged["seats"][:1]}
        response = self.client.put(f"/api/panels/{personal['id']}", json=smaller, headers=self.headers[self.owner["id"]])
        self.assertEqual(response.status_code, 200)
        await collect(await self.start(preset=personal["key"], use_latest_panel=True))
        self.assertEqual(len(self.saved()["messages"][-1]["config"]["seats"]), 1)
        self.assertEqual(self.saved()["messages"][-1]["config"]["quorum"], 1)
        self.assertEqual(self.saved()["messages"][:2], original_messages)
        missing_chairman = {"title": smaller["title"], "seats": smaller["seats"]}
        response = self.client.put(f"/api/panels/{personal['id']}", json=missing_chairman, headers=self.headers[self.owner["id"]])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(db.get_panel(personal["id"], self.owner["id"])["definition"]["chairman"], enlarged["chairman"])

    async def test_avatars_persist_with_identity_and_history_but_never_enter_model_prompts(self):
        image = "data:image/png;base64," + PNG
        definition = panel_definition()
        definition["seats"][0]["avatar"] = image
        definition["seats"][1]["avatar"] = "visionary"
        definition["chairman"]["avatar"] = image
        personal = self.save_panel(definition)
        fetched = self.client.get(f"/api/panels/{personal['id']}", headers=self.headers[self.owner["id"]]).json()
        self.assertEqual(fetched["seats"][0]["avatar"], image)
        self.assertEqual(fetched["chairman"]["avatar"], image)
        for user in (self.other, self.admin):
            self.assertEqual(self.client.get(f"/api/panels/{personal['id']}", headers=self.headers[user["id"]]).status_code, 404)
        await collect(await self.start(preset=personal["key"], max_rounds=0, pause_for_input=False))
        original = copy.deepcopy(self.saved()["messages"])
        renamed = copy.deepcopy(definition)
        renamed["seats"].reverse()
        renamed["seats"][1].update(name="A new name", model="gpt-4.1-mini")
        renamed["chairman"]["avatar"] = "mediator"
        response = self.client.put(f"/api/panels/{personal['id']}", json=renamed, headers=self.headers[self.owner["id"]])
        self.assertEqual(response.status_code, 200)
        await collect(await self.start())
        self.assertEqual(self.saved()["messages"][-1]["config"]["seats"][0]["avatar"], image)
        self.assertEqual(self.saved()["messages"][-1]["config"]["chairman"]["avatar"], image)
        await collect(await self.start(use_latest_panel=True))
        snapshot = self.saved()["messages"][-1]["config"]
        self.assertEqual(snapshot["seats"][0]["avatar"], "visionary")
        self.assertEqual(snapshot["seats"][1]["avatar"], image)
        self.assertEqual(snapshot["seats"][1]["name"], "A new name")
        self.assertEqual(snapshot["chairman"]["avatar"], "mediator")
        self.assertEqual(self.saved()["messages"][:2], original)
        for call in self.seat_calls + self.chair_calls + self.title_calls:
            self.assertNotIn("data:image", call[2])
            self.assertNotIn("data:image", call[3])
            self.assertNotIn(PNG, call[2] + call[3])


if __name__ == "__main__":
    unittest.main()
