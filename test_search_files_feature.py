"""Behavioral tests for the search_files vertical slice.

Covers: real search, case-insensitivity, sensitive exclusion,
deny-before-runner, path validation, truncation, result shape,
bridge + registry routing.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.feature_bridge import build_migrated_tool_handlers
from core.policy import Policy
from core.registry import ToolRegistry
from features.file_access.application.dto.search_files import SearchFilesRequest
from features.file_access.application.use_cases.search_files import SearchFilesUseCase
from features.file_access.composition import build_search_files_controller
from features.file_access.infrastructure.adapters.policy_search_authorization import (
    PolicySearchAuthorizationAdapter,
)


def make_policy(tmp: str) -> Policy:
    policy = Policy()
    policy.workspace = Path(tmp).resolve()
    return policy


def make_controller(tmp: str):
    return build_search_files_controller(make_policy(tmp))


class TestSearchFilesUseCase(unittest.TestCase):
    def test_finds_matches_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("hello needle world\nsecond line\n")
            Path(tmp, "b.txt").write_text("nothing here\n")
            result = make_controller(tmp).handle({"pattern": "needle", "path": "."})
            self.assertTrue(result["ok"])
            self.assertEqual(result["evidence"]["count"], 1)
            m = result["evidence"]["matches"][0]
            self.assertEqual(m["file"], "a.txt")
            self.assertEqual(m["line"], 1)
            self.assertIn("needle", m["content"])

    def test_no_matches_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("hello\n")
            result = make_controller(tmp).handle({"pattern": "zzz-nope", "path": "."})
            self.assertTrue(result["ok"])
            self.assertEqual(result["evidence"]["count"], 0)

    def test_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("Needle here\n")
            result = make_controller(tmp).handle({"pattern": "needle", "path": "."})
            self.assertEqual(result["evidence"]["count"], 1)

    def test_excludes_sensitive_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            secret = Path(tmp, ".env")
            secret.write_text("needle secret\n")
            if not policy.is_sensitive_path(secret):
                self.skipTest("policy does not mark .env sensitive")
            Path(tmp, "ok.txt").write_text("needle public\n")
            result = make_controller(tmp).handle({"pattern": "needle", "path": "."})
            files = [m["file"] for m in result["evidence"]["matches"]]
            self.assertIn("ok.txt", files)
            self.assertNotIn(".env", files)

    def test_invalid_pattern_denied_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            runner = mock.Mock()
            uc = SearchFilesUseCase(
                authorization=PolicySearchAuthorizationAdapter(policy),
                runner=runner,
            )
            result = uc.execute(SearchFilesRequest(pattern="", path="."))
            self.assertFalse(result["ok"])
            runner.run_search.assert_not_called()

    def test_path_escape_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = make_controller(tmp).handle({"pattern": "x", "path": "../.."})
            self.assertFalse(result["ok"])

    def test_nonexistent_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = make_controller(tmp).handle({"pattern": "x", "path": "nope"})
            self.assertFalse(result["ok"])

    def test_max_matches_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "many.txt").write_text("needle\n" * 30)
            result = make_controller(tmp).handle(
                {"pattern": "needle", "path": ".", "max_matches": 5}
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["evidence"]["count"], 5)
            self.assertTrue(result["evidence"]["truncated"])

    def test_result_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("x\n")
            result = make_controller(tmp).handle({"pattern": "x", "path": "."})
            self.assertIn("ok", result)
            self.assertIn("message", result)
            for key in ("pattern", "matches", "count", "truncated"):
                self.assertIn(key, result["evidence"])

    def test_via_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("needle\n")
            handlers = build_migrated_tool_handlers(make_policy(tmp))
            self.assertIn("search_files", handlers)
            result = handlers["search_files"](pattern="needle", path=".")
            self.assertTrue(result["ok"])
            self.assertEqual(result["evidence"]["count"], 1)

    def test_via_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("needle\n")
            registry = ToolRegistry(make_policy(tmp))
            self.assertTrue(registry.has("search_files"))
            result = registry.execute(
                "search_files", {"pattern": "needle", "path": "."}
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["evidence"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
