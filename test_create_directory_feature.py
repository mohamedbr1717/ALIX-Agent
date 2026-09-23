"""Behavioral tests for the create_directory vertical slice."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.feature_bridge import build_migrated_tool_handlers
from core.policy import Policy
from features.file_access.application.dto.create_directory import (
    CreateDirectoryRequest,
)
from features.file_access.application.use_cases.create_directory import (
    CreateDirectoryUseCase,
)
from features.file_access.composition import build_create_directory_controller
from features.file_access.infrastructure.adapters.executor_directory_runner import (
    ExecutorDirectoryRunnerAdapter,
)
from features.file_access.infrastructure.adapters.policy_directory_authorization import (
    PolicyDirectoryAuthorizationAdapter,
)


def make_policy(tmp: str) -> Policy:
    policy = Policy()
    policy.workspace = Path(tmp).resolve()
    return policy


class TestCreateDirectoryFeature(unittest.TestCase):
    def test_controller_wires_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_create_directory_controller(make_policy(tmp))
            result = controller.handle({"path": "newdir"})
            self.assertTrue(result["ok"], result.get("message"))
            self.assertTrue((Path(tmp) / "newdir").is_dir())
            self.assertTrue(result["evidence"].get("verified"))
            self.assertEqual(result["action"], "create_directory")

    def test_nested_directories_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_create_directory_controller(make_policy(tmp))
            result = controller.handle({"path": "a/b/c"})
            self.assertTrue(result["ok"], result.get("message"))
            self.assertTrue((Path(tmp) / "a" / "b" / "c").is_dir())

    def test_existing_directory_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_create_directory_controller(make_policy(tmp))
            first = controller.handle({"path": "docs"})
            second = controller.handle({"path": "docs"})
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])

    def test_sensitive_path_denied_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            # Fixture sanity: .env must really be sensitive under this policy.
            self.assertIsNone(policy.validate_file_path(".env"))
            controller = build_create_directory_controller(policy)
            result = controller.handle({"path": ".env"})
            self.assertFalse(result["ok"])
            self.assertIn("غير مصرَّح", result["message"])
            self.assertFalse((Path(tmp) / ".env").exists())

    def test_path_escape_denied_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_create_directory_controller(make_policy(tmp))
            result = controller.handle({"path": "../outside"})
            self.assertFalse(result["ok"])
            self.assertIn("غير مصرَّح", result["message"])

    def test_empty_path_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_create_directory_controller(make_policy(tmp))
            result = controller.handle({"path": ""})
            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "create_directory")

    def test_use_case_denies_before_runner_is_touched(self):
        class ExplodingRunner:
            def run_create_directory(self, path):
                raise AssertionError("runner must not be called")

        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            use_case = CreateDirectoryUseCase(
                authorization=PolicyDirectoryAuthorizationAdapter(policy),
                runner=ExplodingRunner(),
            )
            result = use_case.execute(CreateDirectoryRequest(path=".env"))
            self.assertFalse(result["ok"])

    def test_registry_handler_goes_through_new_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            handlers = build_migrated_tool_handlers(policy)
            self.assertIn("create_directory", handlers)
            result = handlers["create_directory"](path="via-registry")
            self.assertTrue(result["ok"], result.get("message"))
            self.assertTrue((Path(tmp) / "via-registry").is_dir())


if __name__ == "__main__":
    unittest.main()
