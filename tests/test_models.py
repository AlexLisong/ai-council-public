"""OpenAI-only model policy: retired or unoffered models are remapped everywhere a run can start."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend import config, db, debate, panels, providers
from model_fixtures import provider_registry

OPENAI_CONFIG = {
    "default_preset": "council",
    "presets": {
        "council": {
            "title": "Council",
            "seats": [{"name": "A", "provider": "foundry-openai", "model": "gpt-6-astra", "persona": "a"}],
            "chairman": {"provider": "foundry-openai", "model": "gpt-6-astra"},
        },
        "openai-direct": {
            "title": "Direct",
            "seats": [{"name": "B", "provider": "openai", "model": "gpt-5.1", "persona": "b"}],
            "chairman": {"provider": "openai", "model": "gpt-5.1"},
        },
    },
}

RETIRED_PANEL = {
    "title": "Old council",
    "seats": [
        {"name": "Skeptic", "provider": "foundry-anthropic", "model": "claude-opus-5", "persona": "Doubt.", "avatar": None},
        {"name": "Builder", "provider": "foundry-openai", "model": "gpt-6-astra", "persona": "Build.", "avatar": None},
        {"name": "Router", "provider": "openrouter", "model": "anthropic/claude-sonnet-4.5", "persona": "Route.", "avatar": None},
    ],
    "chairman": {"name": "Chair", "provider": "foundry-anthropic", "model": "claude-fable-5-1", "persona": "", "avatar": None},
}


def configured(providers=("foundry-openai",)):
    """Patch the provider registry and shipped config so tests are hermetic."""
    return [
        patch.object(config, "PROVIDERS", provider_registry(*providers)),
        patch.object(config, "load_council_config", return_value=OPENAI_CONFIG),
        patch.object(debate, "load_council_config", return_value=OPENAI_CONFIG),
    ]


class RetiredModelTests(unittest.TestCase):
    def setUp(self):
        for replacement in configured():
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_retire_models_rewrites_only_retired_members(self):
        definition = copy.deepcopy(RETIRED_PANEL)
        changes = config.retire_models(definition)
        self.assertEqual(len(changes), 3)
        seats = definition["seats"]
        self.assertEqual((seats[0]["provider"], seats[0]["model"]), ("foundry-openai", "gpt-6-astra"))
        self.assertEqual(seats[0]["replaced_model"], "foundry-anthropic/claude-opus-5")
        self.assertNotIn("replaced_model", seats[1])
        self.assertEqual((seats[2]["provider"], seats[2]["model"]), ("foundry-openai", "gpt-6-astra"))
        self.assertEqual(definition["chairman"]["model"], "gpt-6-astra")
        self.assertEqual(config.retire_models(definition), [], "second pass must be a no-op")

    def test_denylist_is_case_insensitive_and_openai_ids_are_never_retired(self):
        for retired in ("Claude-Opus-5", "google/gemini-3-pro-preview", "x-ai/grok-4", "mistralai/mistral-large", "deepseek/deepseek-r1", "meta-llama/llama-4"):
            self.assertTrue(config.is_retired({"provider": "openrouter", "model": retired}), retired)
        for kept in ("gpt-6-astra", "gpt-5.6-sol", "gpt-5.1", "openai/gpt-5.1", "o4-mini"):
            self.assertFalse(config.is_retired({"provider": "openai", "model": kept}), kept)

    def test_unoffered_models_are_replaced_only_at_run_time(self):
        unlisted = {"seats": [{"name": "X", "provider": "openrouter", "model": "some-vendor/new-model", "persona": "x"}],
                    "chairman": {"provider": "foundry-openai", "model": "gpt-6-astra"}}
        durable = copy.deepcopy(unlisted)
        self.assertEqual(config.retire_models(durable), [], "durable rule touches only the denylist")
        panel = debate.normalize_panel(unlisted, "snapshot")
        self.assertEqual((panel["seats"][0]["provider"], panel["seats"][0]["model"]), ("foundry-openai", "gpt-6-astra"))
        self.assertEqual(panel["seats"][0]["replaced_model"], "openrouter/some-vendor/new-model")

    def test_nothing_is_rewritten_when_the_replacement_is_not_configured(self):
        definition = copy.deepcopy(RETIRED_PANEL)
        with patch.object(config, "PROVIDERS", provider_registry("openai")):  # only openai-direct available, replacement is foundry
            self.assertFalse(config.replacement_available())
            self.assertEqual(config.retire_models(definition), [])
            self.assertEqual(definition["seats"][0]["model"], "claude-opus-5")
            panel = debate.normalize_panel(definition, "snapshot")
        self.assertEqual(panel["seats"][0]["model"], "claude-opus-5", "left for validate_models to reject, not silently rewritten")

    def test_no_anthropic_provider_is_ever_registered(self):
        env = {"FOUNDRY_RESOURCE": "r", "FOUNDRY_API_KEY": "k", "ANTHROPIC_API_KEY": "k",
               "ANTHROPIC_FOUNDRY_RESOURCE": "r", "ANTHROPIC_FOUNDRY_API_KEY": "k", "EXTRA_MODELS": "ollama:gpt-oss,foundry-openai:gpt-6-astra"}
        with patch.dict("os.environ", env, clear=True):
            providers = config.build_providers()
        self.assertEqual(set(providers), {"foundry-openai"})
        self.assertTrue(all("kind" not in p for p in providers.values()))

    def test_extra_models_extend_options_for_configured_providers_only(self):
        with patch.object(config, "EXTRA_MODELS", [("ollama", "gpt-oss-120b"), ("foundry-openai", "gpt-4.1-mini")]):
            options = {(o["provider"], o["model"]) for o in config.model_options()}
        self.assertIn(("foundry-openai", "gpt-4.1-mini"), options)
        self.assertNotIn(("ollama", "gpt-oss-120b"), options)

    def test_normalize_panel_remaps_snapshot_without_mutating_input(self):
        panel = debate.normalize_panel(copy.deepcopy(RETIRED_PANEL), "personal:x")
        models = {(m["provider"], m["model"]) for m in [*panel["seats"], panel["chairman"]]}
        self.assertEqual(models, {("foundry-openai", "gpt-6-astra")})
        self.assertEqual(RETIRED_PANEL["seats"][0]["model"], "claude-opus-5")

    def test_renamed_preset_key_still_resolves(self):
        with patch.object(config, "PROVIDERS", provider_registry("foundry-openai", "openai")):
            key, panel = debate.resolve_preset("openrouter-frontier")
            self.assertEqual(key, "openai-direct")
            self.assertEqual(panel["seats"][0]["model"], "gpt-5.1")
        # Without the public OpenAI key the same alias runs on the configured replacement instead of failing.
        key, panel = debate.resolve_preset("openrouter-frontier")
        self.assertEqual((panel["seats"][0]["model"], panel["seats"][0]["replaced_model"]), ("gpt-6-astra", "openai/gpt-5.1"))

    def test_migrated_definition_round_trips_through_the_save_schema(self):
        definition = copy.deepcopy(RETIRED_PANEL)
        config.retire_models(definition)
        request = panels.PanelRequest(**definition)
        self.assertEqual(request.seats[0].replaced_model, "foundry-anthropic/claude-opus-5")


class ShippedConfigTests(unittest.TestCase):
    def test_shipped_config_uses_only_openai_models(self):
        cfg = config.load_council_config()
        for key, preset in cfg["presets"].items():
            for member in [*preset["seats"], preset["chairman"]]:
                self.assertFalse(config.is_retired(member), f"{key}: {member['provider']}/{member['model']}")
                self.assertIn(member["provider"], {"foundry-openai", "openai"}, key)
                self.assertTrue(member["model"].startswith(("gpt-",)), f"{key}: {member['model']}")

    def test_replacement_model_is_a_shipped_foundry_choice(self):
        cfg = config.load_council_config()
        with patch.object(config, "PROVIDERS", provider_registry("foundry-openai")):
            self.assertTrue(config.replacement_available(config.model_options(cfg)))


class OpenAIOnlyPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = provider_registry("foundry-openai", "openai", "openrouter")
        self.registry.update({
            "custom": {"base_url": "https://proxy.example/v1", "auth": "bearer"},
            "ollama": {"base_url": "http://localhost:11434/v1", "auth": "bearer"},
            "anthropic": {"base_url": "https://api.anthropic.com/v1", "auth": "bearer"},
        })
        self.cfg = copy.deepcopy(OPENAI_CONFIG)
        self.bad_pairs = [
            ("foundry-openai", "claude-opus-5"), ("foundry-openai", "my-gpt-deployment"),
            ("foundry-openai", "gpt-6-astra-claude"), ("foundry-openai", "gpt-secret-vendor"),
            ("openai", "anthropic/claude-sonnet-4.5"), ("openai", "gpt-5.1-unknown"),
            ("openrouter", "anthropic/claude-opus-5"), ("openrouter", "openai/claude-opus-5"),
            ("openrouter", "some-vendor/new-model"), ("openrouter", "gpt-5.1"),
            ("custom", "gpt-5.1"), ("ollama", "gpt-oss-120b"), ("anthropic", "gpt-5.1"),
        ]
        for index, (provider, model) in enumerate(self.bad_pairs):
            self.cfg["presets"][f"unsafe{index}"] = {
                "seats": [{"name": "Unsafe", "provider": provider, "model": model, "persona": "Test"}],
                "chairman": {"provider": provider, "model": model},
            }
        for replacement in (
            patch.object(config, "PROVIDERS", self.registry),
            patch.object(config, "EXTRA_MODELS", [*self.bad_pairs, ("openrouter", "openai/gpt-5.1")]),
            patch.object(config, "load_council_config", return_value=self.cfg),
            patch.object(debate, "load_council_config", return_value=self.cfg),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_unsafe_config_extra_models_and_panel_saves_cannot_extend_the_positive_policy(self):
        choices = {(option["provider"], option["model"]) for option in config.model_options()}
        self.assertEqual(choices, {("foundry-openai", "gpt-6-astra"), ("openai", "gpt-5.1"), ("openrouter", "openai/gpt-5.1")})
        for key, preset in self.cfg["presets"].items():
            if key.startswith("unsafe"):
                with self.assertRaises(ValueError):
                    panels.validate_models(preset)
        public = config.public_config()
        self.assertTrue(all(not preset["available"] for preset in public["presets"] if preset["key"].startswith("unsafe")))
        self.assertNotIn("custom", public["providers"])

    def test_compatible_endpoint_overrides_are_rejected_in_registry_and_options(self):
        for url in (
            "https://api.anthropic.com/v1", "https://api.openai.com.proxy.example/v1",
            "http://api.openai.com/v1", "https://api.openai.com@proxy.example/v1",
            "https://api.openai.com/v1?route=anthropic", "https://api.openai.com/v1/../proxy",
        ):
            with self.subTest(url=url), patch.dict("os.environ", {
                "OPENAI_API_KEY": "unused", "OPENAI_BASE_URL": url,
                "CUSTOM_OPENAI_BASE_URL": "https://custom.example/v1", "OLLAMA_BASE_URL": "http://localhost/v1",
            }, clear=True):
                self.assertEqual(config.build_providers(), {})
            with patch.dict(self.registry["openai"], {"base_url": url}):
                self.assertNotIn({"provider": "openai", "model": "gpt-5.1"}, config.model_options())

    async def test_every_unsafe_nonstreaming_streaming_and_title_call_is_blocked_before_network(self):
        with patch.object(providers, "_get_client") as client:
            for provider, model in [*self.bad_pairs, ("openai", "gpt-4.1")]:  # The last model is known but not offered.
                self.assertIsNone(await providers.chat(provider, model, "system", "user"))
                with self.assertRaises(providers.ChatError):
                    await anext(providers.stream_chat(provider, model, []))
                self.assertEqual(await debate.generate_title("title", chairman={"provider": provider, "model": model}), "New Conversation")
            client.assert_not_called()

    async def test_unsafe_chairman_and_seats_in_direct_run_config_are_guarded_at_dispatch(self):
        calls = []

        def respond(request):
            calls.append(json.loads(request.content)["model"])
            return httpx.Response(200, json={"choices": [{"message": {"content": "An opening position"}, "finish_reason": "stop"}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(client.aclose)
        with patch.object(providers, "_get_client", return_value=client):
            runtime = debate.resolve_debate_config("council", max_rounds=0, pause_for_input=False)
            runtime["chairman"] = {"provider": "foundry-openai", "model": "claude-opus-5"}
            events = [event async for event in debate.run_debate("question", config=runtime)]
            self.assertEqual(calls, ["gpt-6-astra"])
            self.assertIn("did not return a synthesis", events[-1]["data"]["response"])
            calls.clear()
            runtime["seats"][0]["model"] = "my-gpt-deployment"
            events = [event async for event in debate.run_debate("question", config=runtime)]
            self.assertEqual(events[-1]["type"], "error")
            self.assertEqual(calls, [])

    async def test_trusted_endpoint_policy_cannot_be_bypassed_after_selection(self):
        with patch.dict(self.registry["foundry-openai"], {"base_url": "https://proxy.example/openai/v1"}), patch.object(providers, "_get_client") as client:
            self.assertIsNone(await providers.chat("foundry-openai", "gpt-6-astra", "system", "user"))
            with self.assertRaises(providers.ChatError):
                await anext(providers.stream_chat("foundry-openai", "gpt-6-astra", []))
            client.assert_not_called()


class RetiredModelMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for replacement in (patch.object(db, "DB_PATH", str(Path(self.temp.name) / "council.db")), *configured()):
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db()
        self.owner = db.create_user("owner", "unused")

    def test_migration_rewrites_saved_panels_once_and_keeps_ordering(self):
        old = db.create_panel("11111111-1111-1111-1111-111111111111", self.owner["id"], copy.deepcopy(RETIRED_PANEL))
        fine = copy.deepcopy(RETIRED_PANEL)
        config.retire_models(fine)
        db.create_panel("22222222-2222-2222-2222-222222222222", self.owner["id"], fine)

        self.assertEqual(db.migrate_retired_models(), 1)
        stored = db.get_panel(old["id"], self.owner["id"])
        self.assertEqual({m["model"] for m in [*stored["definition"]["seats"], stored["definition"]["chairman"]]}, {"gpt-6-astra"})
        self.assertEqual(stored["updated_at"], old["updated_at"], "a data fix must not reorder the user's library")
        self.assertEqual(db.migrate_retired_models(), 0)

    def test_migration_skips_bad_rows_and_refuses_unconfigured_replacement(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO panels (id, owner_id, created_at, updated_at, definition) VALUES (?, ?, ?, ?, ?)",
                         ("33333333-3333-3333-3333-333333333333", self.owner["id"], db.now_iso(), db.now_iso(), "not json"))
        db.create_panel("11111111-1111-1111-1111-111111111111", self.owner["id"], copy.deepcopy(RETIRED_PANEL))
        with patch.object(config, "PROVIDERS", provider_registry("openai")):
            self.assertEqual(db.migrate_retired_models(), 0, "no rewrite when the replacement cannot run")
        self.assertEqual(db.migrate_retired_models(), 1, "the malformed row is skipped, the good one migrates")

    def test_select_panel_remaps_an_old_turn_snapshot(self):
        prior = {"preset": "foundry-mixed", "preset_title": "Old", **copy.deepcopy(RETIRED_PANEL)}
        key, selected = panels.select_panel(self.owner["id"], None, prior, use_latest=False)
        self.assertEqual(key, "foundry-mixed")
        self.assertEqual({m["model"] for m in [*selected["seats"], selected["chairman"]]}, {"gpt-6-astra"})


if __name__ == "__main__":
    unittest.main()
