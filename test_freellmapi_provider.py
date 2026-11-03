"""Behavioral tests for the FreeLLMAPI remote provider in core/llm.py.

FreeLLMAPI is a self-hosted router on the same machine
(http://127.0.0.1:3001/v1) that stacks free provider tiers behind one
OpenAI-compatible endpoint. Provider selection is driven by
REMOTE_PROVIDER=freellmapi (+ FREELLMAPI_* vars). The default model is
"auto": the router picks the upstream model per request.

No real network: the OpenAI client is mocked and the .env file read is
neutralized.
"""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest import mock

from core.llm import HybridLLM

PROVIDER_VARS = (
    "REMOTE_PROVIDER",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "FREELLMAPI_KEY",
    "FREELLMAPI_MODEL",
)


@contextmanager
def controlled_env(env):
    """Run with a fixed env, empty .env file, and mocked OpenAI client."""
    with mock.patch(
        "core.llm.dotenv_values", return_value={}
    ), mock.patch(
        "core.llm.OpenAI"
    ) as client_cls, mock.patch.dict(
        "os.environ", {}, clear=False
    ):
        for var in PROVIDER_VARS:
            os.environ.pop(var, None)
        os.environ.update(env)
        yield client_cls


class TestFreeLLMAPIProvider(unittest.TestCase):
    def test_freellmapi_provider_configures_local_router_client(self):
        with controlled_env(
            {
                "REMOTE_PROVIDER": "freellmapi",
                "FREELLMAPI_KEY": "freellmapi-test-key",
            }
        ) as client_cls:
            h = HybridLLM(use_remote=True)
        self.assertEqual(h.provider, "freellmapi")
        self.assertEqual(h.remote_label, "FreeLLMAPI")
        # "auto" = the router chooses the upstream model per request.
        self.assertEqual(h.model, "auto")
        client_cls.assert_called_once()
        kwargs = client_cls.call_args[1]
        self.assertEqual(
            kwargs["base_url"], "http://127.0.0.1:3001/v1"
        )
        self.assertEqual(kwargs["api_key"], "freellmapi-test-key")

    def test_freellmapi_custom_model_is_respected(self):
        with controlled_env(
            {
                "REMOTE_PROVIDER": "freellmapi",
                "FREELLMAPI_KEY": "freellmapi-test-key",
                "FREELLMAPI_MODEL": "auto:quality",
            }
        ):
            h = HybridLLM(use_remote=True)
        self.assertEqual(h.model, "auto:quality")

    def test_freellmapi_without_key_disables_remote_fail_closed(self):
        with controlled_env(
            {"REMOTE_PROVIDER": "freellmapi"}
        ) as client_cls:
            h = HybridLLM(use_remote=True)
        self.assertFalse(h.use_remote)
        self.assertIsNone(h.client)
        client_cls.assert_not_called()

    def test_freellmapi_status_reports_provider(self):
        with controlled_env(
            {
                "REMOTE_PROVIDER": "freellmapi",
                "FREELLMAPI_KEY": "freellmapi-test-key",
            }
        ):
            h = HybridLLM(use_remote=True)
        st = h.status()
        self.assertEqual(st["remote_provider"], "freellmapi")
        self.assertEqual(st["remote_model"], "auto")
        self.assertTrue(st["remote_enabled"])
        self.assertTrue(st["remote_configured"])

    def test_safe_error_redacts_unified_key(self):
        with controlled_env({}):
            h = HybridLLM(use_remote=False)
        h.api_key = "freellmapi-secret-456"
        out = h._safe_error(
            Exception("failed with freellmapi-secret-456 inside")
        )
        self.assertNotIn("freellmapi-secret-456", out)
        self.assertIn("***REDACTED***", out)

    def test_existing_providers_unaffected(self):
        # Regression spot-checks: adding the third entry must not move
        # the default or the Groq wiring.
        with controlled_env(
            {"OPENROUTER_API_KEY": "or-key"}
        ) as client_cls:
            h = HybridLLM(use_remote=True)
        self.assertEqual(h.provider, "openrouter")
        kwargs = client_cls.call_args[1]
        self.assertEqual(
            kwargs["base_url"], "https://openrouter.ai/api/v1"
        )
        with controlled_env(
            {
                "REMOTE_PROVIDER": "groq",
                "GROQ_API_KEY": "gsk-test",
                "GROQ_MODEL": "openai/gpt-oss-120b",
            }
        ) as client_cls:
            h = HybridLLM(use_remote=True)
        self.assertEqual(h.provider, "groq")
        kwargs = client_cls.call_args[1]
        self.assertEqual(
            kwargs["base_url"], "https://api.groq.com/openai/v1"
        )


if __name__ == "__main__":
    unittest.main()
