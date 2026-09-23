"""Behavioral tests for the web_search/web_fetch vertical slice.

All tests are network-free: they exercise the real SSRF guard
(`tools/web.py::_validate_url`), validation, deny-before-runner,
coercion, and wiring. Live provider/HTTP paths are verified manually
(runtime check through the migrated path).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.feature_bridge import build_migrated_tool_handlers
from core.policy import Policy
from core.registry import ToolRegistry
from features.web.application.dto.web_fetch import WebFetchRequest
from features.web.application.dto.web_search import WebSearchRequest
from features.web.application.use_cases.web_fetch import WebFetchUseCase
from features.web.application.use_cases.web_search import WebSearchUseCase
from features.web.composition import (
    build_web_fetch_controller,
    build_web_search_controller,
)
from features.web.infrastructure.adapters.web_fetch_authorization import (
    WebFetchAuthorizationAdapter,
)
from features.web.infrastructure.adapters.web_search_authorization import (
    WebSearchAuthorizationAdapter,
)
from features.web.infrastructure.adapters.web_tools_fetch_runner import (
    WebToolsFetchRunnerAdapter,
)
from features.web.infrastructure.adapters.web_tools_search_runner import (
    WebToolsSearchRunnerAdapter,
)


def make_policy() -> Policy:
    policy = Policy()
    policy.workspace = Path(tempfile.mkdtemp()).resolve()
    return policy


class TestWebSearchSlice(unittest.TestCase):
    def test_empty_query_denied_before_runner(self):
        runner = mock.Mock()
        uc = WebSearchUseCase(
            authorization=WebSearchAuthorizationAdapter(), runner=runner
        )
        for q in ("", "   "):
            result = uc.execute(WebSearchRequest(query=q))
            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "web_search")
        runner.run_search.assert_not_called()

    def test_authorization(self):
        auth = WebSearchAuthorizationAdapter()
        self.assertTrue(auth.can_search("hello"))
        self.assertFalse(auth.can_search(""))
        self.assertFalse(auth.can_search("   "))
        self.assertFalse(auth.can_search(None))

    def test_use_case_returns_runner_result(self):
        expected = {"ok": True, "action": "web_search", "message": "m",
                    "evidence": {}}
        runner = mock.Mock()
        runner.run_search.return_value = expected
        uc = WebSearchUseCase(
            authorization=WebSearchAuthorizationAdapter(), runner=runner
        )
        self.assertEqual(uc.execute(WebSearchRequest(query="hello")), expected)
        runner.run_search.assert_called_once_with("hello", 5)

    def test_controller_coerces_max_results(self):
        with mock.patch.object(
            WebToolsSearchRunnerAdapter, "run_search",
            return_value={"ok": True},
        ) as m:
            ctrl = build_web_search_controller()
            ctrl.handle({"query": "hello", "max_results": "abc"})
            m.assert_called_once_with("hello", 5)
            ctrl.handle({"query": "hello", "max_results": 3})
            m.assert_called_with("hello", 3)

    def test_dto_defaults(self):
        self.assertEqual(WebSearchRequest(query="x").max_results, 5)


class TestWebFetchSlice(unittest.TestCase):
    def test_private_ips_denied_before_runner(self):
        """Real SSRF guard: literal private IPs need no DNS/network."""
        runner = mock.Mock()
        uc = WebFetchUseCase(
            authorization=WebFetchAuthorizationAdapter(), runner=runner
        )
        for url in (
            "http://127.0.0.1/",
            "http://192.168.1.1/x",
            "http://10.0.0.5/",
        ):
            result = uc.execute(WebFetchRequest(url=url))
            self.assertFalse(result["ok"], url)
            self.assertEqual(result["action"], "web_fetch")
        runner.run_fetch.assert_not_called()

    def test_bad_scheme_denied(self):
        runner = mock.Mock()
        uc = WebFetchUseCase(
            authorization=WebFetchAuthorizationAdapter(), runner=runner
        )
        result = uc.execute(WebFetchRequest(url="ftp://example.com/x"))
        self.assertFalse(result["ok"])
        runner.run_fetch.assert_not_called()

    def test_empty_url_denied(self):
        runner = mock.Mock()
        uc = WebFetchUseCase(
            authorization=WebFetchAuthorizationAdapter(), runner=runner
        )
        for url in ("", "   "):
            result = uc.execute(WebFetchRequest(url=url))
            self.assertFalse(result["ok"])
        runner.run_fetch.assert_not_called()

    def test_authorization(self):
        auth = WebFetchAuthorizationAdapter()
        self.assertFalse(auth.can_fetch("http://127.0.0.1/"))
        self.assertFalse(auth.can_fetch("ftp://example.com/"))
        self.assertFalse(auth.can_fetch(""))
        self.assertFalse(auth.can_fetch(None))

    def test_controller_coerces_max_chars(self):
        with mock.patch.object(
            WebFetchAuthorizationAdapter, "can_fetch", return_value=True
        ), mock.patch.object(
            WebToolsFetchRunnerAdapter, "run_fetch",
            return_value={"ok": True},
        ) as m:
            ctrl = build_web_fetch_controller()
            ctrl.handle({"url": "https://example.com", "max_chars": "xyz"})
            m.assert_called_once_with("https://example.com", 8000)

    def test_use_case_returns_runner_result(self):
        expected = {"ok": True, "action": "web_fetch", "message": "m",
                    "evidence": {}}
        with mock.patch.object(
            WebFetchAuthorizationAdapter, "can_fetch", return_value=True
        ):
            runner = mock.Mock()
            runner.run_fetch.return_value = expected
            uc = WebFetchUseCase(
                authorization=WebFetchAuthorizationAdapter(), runner=runner
            )
            result = uc.execute(WebFetchRequest(url="https://example.com"))
            self.assertEqual(result, expected)

    def test_dto_defaults(self):
        self.assertEqual(WebFetchRequest(url="x").max_chars, 8000)


class TestWebWiring(unittest.TestCase):
    def test_bridge_registers_web_handlers(self):
        handlers = build_migrated_tool_handlers(make_policy())
        self.assertIn("web_search", handlers)
        self.assertIn("web_fetch", handlers)

    def test_registry_registers_web_tools(self):
        registry = ToolRegistry(make_policy())
        self.assertTrue(registry.has("web_search"))
        self.assertTrue(registry.has("web_fetch"))


if __name__ == "__main__":
    unittest.main()
