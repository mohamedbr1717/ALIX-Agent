"""Behavioral tests for the final migration: verify_file (file_access)
and remember_fact (new features/memory slice).

remember_fact tests use a mock Memory so the live memory.json is never
touched. verify_file tests use a real tmp workspace through the full
slice path.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.feature_bridge import build_migrated_tool_handlers
from core.memory import Memory
from core.policy import Policy
from core.registry import ToolRegistry
from features.file_access.application.dto.verify_file import VerifyFileRequest
from features.file_access.application.use_cases.verify_file import (
    VerifyFileUseCase,
)
from features.file_access.composition import build_verify_file_controller
from features.file_access.infrastructure.adapters.executor_file_verification_runner import (
    ExecutorFileVerificationRunnerAdapter,
)
from features.file_access.infrastructure.adapters.policy_file_verification_authorization import (
    PolicyFileVerificationAuthorizationAdapter,
)
from features.memory.application.dto.remember_fact import RememberFactRequest
from features.memory.application.use_cases.remember_fact import (
    RememberFactUseCase,
)
from features.memory.composition import build_remember_fact_controller
from features.memory.infrastructure.adapters.fact_authorization import (
    FactAuthorizationAdapter,
)
from features.memory.infrastructure.adapters.memory_fact_runner import (
    MemoryFactRunnerAdapter,
)


def make_policy() -> Policy:
    policy = Policy()
    policy.workspace = Path(tempfile.mkdtemp()).resolve()
    return policy


class TestRememberFactSlice(unittest.TestCase):
    def test_empty_fact_denied_before_runner(self):
        runner = mock.Mock()
        uc = RememberFactUseCase(
            authorization=FactAuthorizationAdapter(), runner=runner
        )
        for f in ("", "   "):
            result = uc.execute(RememberFactRequest(fact=f))
            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "remember_fact")
        runner.run_remember.assert_not_called()

    def test_fact_saved_through_memory(self):
        memory = mock.Mock()
        memory.add_fact.return_value = True
        runner = MemoryFactRunnerAdapter(memory)
        result = runner.run_remember("the sky is blue", False)
        memory.add_fact.assert_called_once_with("the sky is blue")
        memory.add_preference.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertTrue(result["evidence"]["saved"])
        self.assertEqual(result["evidence"]["type"], "fact")

    def test_preference_saved_through_memory(self):
        memory = mock.Mock()
        memory.add_preference.return_value = True
        runner = MemoryFactRunnerAdapter(memory)
        result = runner.run_remember("likes tea", True)
        memory.add_preference.assert_called_once_with("likes tea")
        memory.add_fact.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["evidence"]["type"], "preference")

    def test_failed_save_reports_not_ok(self):
        memory = mock.Mock()
        memory.add_fact.return_value = False
        runner = MemoryFactRunnerAdapter(memory)
        result = runner.run_remember("x", False)
        self.assertFalse(result["ok"])
        self.assertFalse(result["evidence"]["saved"])

    def test_use_case_delegates_to_runner(self):
        expected = {"ok": True, "evidence": {"saved": True, "type": "fact"}}
        runner = mock.Mock()
        runner.run_remember.return_value = expected
        uc = RememberFactUseCase(
            authorization=FactAuthorizationAdapter(), runner=runner
        )
        result = uc.execute(
            RememberFactRequest(fact="hello", is_preference=False)
        )
        self.assertEqual(result, expected)
        runner.run_remember.assert_called_once_with("hello", False)

    def test_controller_builds_request(self):
        with mock.patch.object(
            MemoryFactRunnerAdapter, "run_remember",
            return_value={"ok": True},
        ) as m:
            ctrl = build_remember_fact_controller(memory=mock.Mock())
            ctrl.handle({"fact": "  hello  ", "is_preference": True})
            m.assert_called_once_with("hello", True)

    def test_composition_default_memory(self):
        # No memory injected -> builds a real Memory on the default store.
        ctrl = build_remember_fact_controller()
        runner = ctrl._use_case._runner
        self.assertIsInstance(runner._memory, Memory)


class TestVerifyFileSlice(unittest.TestCase):
    def _controller(self, tmp: str):
        policy = Policy()
        policy.workspace = Path(tmp).resolve()
        return build_verify_file_controller(policy), policy

    def test_real_file_verified_through_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hi")
            ctrl, _ = self._controller(tmp)
            result = ctrl.handle({"path": "a.txt"})
            self.assertTrue(result["ok"])
            self.assertTrue(result["evidence"]["verified"])
            self.assertTrue(result["evidence"]["is_file"])
            self.assertEqual(result["evidence"]["size_bytes"], 2)

    def test_missing_file_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctrl, _ = self._controller(tmp)
            result = ctrl.handle({"path": "nope.txt"})
            self.assertFalse(result["ok"])
            self.assertFalse(result["evidence"]["verified"])

    def test_escape_denied_before_runner(self):
        policy = make_policy()
        runner = mock.Mock()
        uc = VerifyFileUseCase(
            authorization=PolicyFileVerificationAuthorizationAdapter(policy),
            runner=runner,
        )
        result = uc.execute(VerifyFileRequest(path="../evil.txt"))
        self.assertFalse(result["ok"])
        runner.run_verification.assert_not_called()

    def test_use_case_delegates_to_runner(self):
        policy = make_policy()
        expected = {"ok": True, "action": "verify_file"}
        runner = mock.Mock(return_value=None)
        runner.run_verification.return_value = expected
        uc = VerifyFileUseCase(
            authorization=PolicyFileVerificationAuthorizationAdapter(policy),
            runner=runner,
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("x")
            policy.workspace = Path(tmp).resolve()
            result = uc.execute(VerifyFileRequest(path="a.txt"))
        self.assertEqual(result, expected)


class TestFinalWiring(unittest.TestCase):
    def test_bridge_registers_both(self):
        handlers = build_migrated_tool_handlers(
            make_policy(), memory=mock.Mock()
        )
        self.assertIn("verify_file", handlers)
        self.assertIn("remember_fact", handlers)

    def test_registry_registers_both(self):
        registry = ToolRegistry(make_policy())
        self.assertTrue(registry.has("verify_file"))
        self.assertTrue(registry.has("remember_fact"))

    def test_remember_fact_through_registry_handler(self):
        # Registry path builds its own default Memory; use a mock runner
        # via the handler to avoid touching the live store.
        policy = make_policy()
        handlers = build_migrated_tool_handlers(policy, memory=mock.Mock())
        result = handlers["remember_fact"](fact="")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
