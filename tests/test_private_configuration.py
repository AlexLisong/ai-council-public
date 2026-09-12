"""Private deployment names and bootstrap credentials never become public output."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend import auth, config, db, providers
from model_fixtures import provider_registry


class DeploymentMappingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = provider_registry("foundry-openai")
        self.registry["foundry-openai"]["model_deployments"] = {
            "gpt-5.1": "private-test-deployment",
        }
        self.definition = {
            "default_preset": "test",
            "presets": {"test": {
                "seats": [{"name": "Test", "provider": "foundry-openai", "model": "gpt-5.1", "persona": "Test"}],
                "chairman": {"provider": "foundry-openai", "model": "gpt-5.1"},
            }},
        }
        for replacement in (
            patch.object(config, "PROVIDERS", self.registry),
            patch.object(config, "load_council_config", return_value=self.definition),
            patch.object(config, "EXTRA_MODELS", []),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_mapping_stays_private_and_alias_cannot_be_selected(self):
        public = config.public_config()
        self.assertNotIn("private-test-deployment", json.dumps(public))
        self.assertEqual(public["model_options"], [{"provider": "foundry-openai", "model": "gpt-5.1"}])
        with self.assertRaises(providers.ChatError):
            providers._provider_for("foundry-openai", "private-test-deployment")

    def test_mapping_validates_canonical_models_and_redacts_invalid_values(self):
        invalid = [[], {"unverified-model": "secret-value"}, {"gpt-5.1": "secret value"}, {"gpt-5.1": None}]
        for mapping in invalid:
            with self.subTest(mapping=mapping), patch.dict("os.environ", {"FOUNDRY_DEPLOYMENT_MAP": json.dumps(mapping)}):
                with self.assertRaises(ValueError) as caught:
                    config.foundry_deployments()
                self.assertNotIn("secret", str(caught.exception))
        with patch.dict("os.environ", {
            "FOUNDRY_RESOURCE": "example-resource", "FOUNDRY_API_KEY": "unused",
            "FOUNDRY_DEPLOYMENT_MAP": '{"gpt-5.1":"example-deployment"}',
        }, clear=True):
            self.assertEqual(config.build_providers()["foundry-openai"]["model_deployments"], {"gpt-5.1": "example-deployment"})

    async def test_both_transports_translate_only_after_public_model_validation(self):
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append(body)
            if body.get("stream"):
                frame = {"choices": [{"delta": {"content": "A response"}, "finish_reason": "stop"}]}
                return httpx.Response(200, text="data: " + json.dumps(frame) + "\n\n", headers={"Content-Type": "text/event-stream"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "A response"}, "finish_reason": "stop"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(providers, "_get_client", return_value=client):
                self.assertEqual(await providers.chat("foundry-openai", "gpt-5.1", "system", "user"), "A response")
                self.assertEqual([piece async for piece in providers.stream_chat("foundry-openai", "gpt-5.1", [])], ["A response"])
                self.assertIsNone(await providers.chat("foundry-openai", "private-test-deployment", "system", "user"))
        self.assertEqual([body["model"] for body in calls], ["private-test-deployment", "private-test-deployment"])

    async def test_provider_error_body_is_not_logged(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(400, text="private-provider-response")
        )) as client:
            with patch.object(providers, "_get_client", return_value=client), self.assertLogs("council.providers") as logs:
                self.assertIsNone(await providers.chat("foundry-openai", "gpt-5.1", "system", "user"))
        self.assertNotIn("private-provider-response", "\n".join(logs.output))
        self.assertIn("HTTP 400", "\n".join(logs.output))


class AdministratorBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for replacement in (
            patch.object(db, "DB_PATH", str(Path(self.temp.name) / "council.db")),
            patch.object(db, "DATA_DIR", str(Path(self.temp.name) / "legacy")),
            patch.object(auth, "ADMIN_USERNAME", "test-admin"),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_missing_password_cannot_create_an_unknown_or_logged_password(self):
        with patch.object(auth, "ADMIN_PASSWORD", None):
            with self.assertRaisesRegex(RuntimeError, "Set ADMIN_PASSWORD"):
                auth.bootstrap_admin()
        self.assertIsNone(db.get_user_by_username("test-admin"))

    def test_password_is_hashed_and_never_logged_and_restart_needs_no_password(self):
        password = "local-test-password-only"
        with patch.object(auth, "ADMIN_PASSWORD", password), self.assertLogs("council.auth") as logs:
            auth.bootstrap_admin()
        self.assertNotIn(password, "\n".join(logs.output))
        administrator = db.get_user_by_username("test-admin")
        self.assertNotEqual(administrator["password_hash"], password)
        self.assertTrue(auth.verify_password(password, administrator["password_hash"]))
        with patch.object(auth, "ADMIN_PASSWORD", None):
            auth.bootstrap_admin()
        self.assertEqual(db.get_user_by_username("test-admin")["id"], administrator["id"])
