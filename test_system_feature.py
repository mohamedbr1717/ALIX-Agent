"""Behavioral tests for the system vertical slice."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.feature_bridge import build_migrated_tool_handlers
from core.policy import Policy
from features.system.composition import (
    build_git_status_controller,
    build_system_info_controller,
)


def make_policy(tmp: str) -> Policy:
    policy = Policy()
    policy.workspace = Path(tmp).resolve()
    return policy


def git_available() -> bool:
    try:
        r = subprocess.run(
            ["git", "--version"], capture_output=True, timeout=10
        )
        return r.returncode == 0
    except Exception:
        return False


class TestSystemInfo(unittest.TestCase):
    def test_controller_wires_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_system_info_controller(make_policy(tmp))
            result = controller.handle({})
            self.assertEqual(result["action"], "system_info")
            self.assertIsInstance(result["evidence"], dict)
            # Only the two known probes may appear; on Android `free`
            # may be missing, so `memory` is optional.
            self.assertLessEqual(set(result["evidence"]), {"uname", "memory"})

    def test_probe_results_have_bounded_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_system_info_controller(make_policy(tmp))
            result = controller.handle({})
            for probe in result["evidence"].values():
                self.assertIn("returncode", probe)
                self.assertIn("stdout", probe)
                self.assertIn("stderr", probe)
                self.assertLessEqual(len(probe["stdout"]), 1500)
                self.assertLessEqual(len(probe["stderr"]), 1000)

    def test_denied_when_policy_blocks_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            controller = build_system_info_controller(policy)
            with patch.object(policy, "command_allowed", return_value=False):
                result = controller.handle({})
            self.assertFalse(result["ok"])
            self.assertIn("غير مصرَّح", result["message"])
            self.assertEqual(result["action"], "system_info")


class TestGitStatus(unittest.TestCase):
    def test_disallowed_action_denied_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_git_status_controller(make_policy(tmp))
            result = controller.handle({"action": "push"})
            self.assertFalse(result["ok"])
            self.assertIn("غير مسموحة", result["message"])
            self.assertEqual(result["action"], "git_status")

    def test_non_string_action_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_git_status_controller(make_policy(tmp))
            result = controller.handle({"action": 123})
            self.assertFalse(result["ok"])
            self.assertIn("غير صالح", result["message"])

    def test_action_defaults_to_status(self):
        if not git_available():
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["git", "init"], cwd=tmp, capture_output=True, timeout=30
            )
            controller = build_git_status_controller(make_policy(tmp))
            result = controller.handle({})
            self.assertTrue(result["ok"], result.get("message"))
            self.assertEqual(result["evidence"]["git_action"], "status")
            self.assertTrue(result["evidence"]["read_only"])

    def test_end_to_end_in_real_git_repo(self):
        if not git_available():
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["git", "init"], cwd=tmp, capture_output=True, timeout=30
            )
            controller = build_git_status_controller(make_policy(tmp))
            result = controller.handle({"action": "status"})
            self.assertTrue(result["ok"], result.get("message"))
            self.assertEqual(result["evidence"]["git_action"], "status")
            self.assertTrue(result["evidence"]["read_only"])
            self.assertTrue(result["evidence"]["verified"])

    def test_fails_closed_outside_git_repo(self):
        if not git_available():
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_git_status_controller(make_policy(tmp))
            result = controller.handle({"action": "status"})
            # Not a git repo: the real git binary fails -> ok False,
            # never an exception, never a shell.
            self.assertFalse(result["ok"])


class TestSystemBridgeWiring(unittest.TestCase):
    def test_handlers_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            handlers = build_migrated_tool_handlers(make_policy(tmp))
            self.assertIn("system_info", handlers)
            self.assertIn("git_status", handlers)


if __name__ == "__main__":
    unittest.main()
