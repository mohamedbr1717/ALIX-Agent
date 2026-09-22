"""Behavioral tests for the run_command vertical slice migration.

run_command is a privileged tool: the migrated slice must preserve the
live SafeExecutor behavior exactly -- allowlist gate, argv parsing
without shell, bounded execution, and the unified result envelope.
The storage... the runner adapter DELEGATES to SafeExecutor, so the
parity test below proves the slice never changes a decision.
"""
import unittest

from core.executor import SafeExecutor
from core.policy import Policy
from features.command_execution.application.dto.run_command import (
    RunCommandRequest,
)
from features.command_execution.application.use_cases.run_command import (
    RunCommandUseCase,
)
from features.command_execution.composition import build_run_command_controller
from features.command_execution.infrastructure.adapters.executor_command_runner import (
    ExecutorCommandRunnerAdapter,
)
from features.command_execution.infrastructure.adapters.policy_command_authorization import (
    PolicyCommandAuthorizationAdapter,
)


class RunCommandSliceTestBase(unittest.TestCase):
    def setUp(self):
        self.policy = Policy()
        self.runner = ExecutorCommandRunnerAdapter(self.policy)
        self.authorization = PolicyCommandAuthorizationAdapter(self.policy)
        self.use_case = RunCommandUseCase(
            runner=self.runner,
            authorization=self.authorization,
        )

    def _executor(self):
        return SafeExecutor(self.policy)


class TestRunCommandUseCase(RunCommandSliceTestBase):
    def test_rejects_blank_command(self):
        for bad in ("", "   "):
            result = self.use_case.execute(RunCommandRequest(command=bad))
            self.assertFalse(result["ok"])

    def test_rejects_non_string_command(self):
        result = self.use_case.execute(RunCommandRequest(command=None))
        self.assertFalse(result["ok"])

    def test_denied_command_never_reaches_runner(self):
        class ExplodingRunner:
            def run_command(self, command):
                raise AssertionError(
                    "runner must not be touched when unauthorized"
                )

        use_case = RunCommandUseCase(
            runner=ExplodingRunner(),
            authorization=self.authorization,
        )
        # A command the policy will never allow.
        result = use_case.execute(
            RunCommandRequest(command="rm -rf / --no-preserve-root")
        )
        self.assertFalse(result["ok"])

    def test_denial_envelope_matches_schema_contract(self):
        result = self.use_case.execute(RunCommandRequest(command=""))
        for key in (
            "ok", "action", "message", "stdout", "stderr",
            "returncode", "evidence", "duration",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["action"], "run_command")

    def test_old_vs_new_decision_parity(self):
        """The slice must never change SafeExecutor's decision.

        Battery covers: a (probably) allowed command, a denied one,
        blank input, and a missing executable. Whatever the policy
        decides, both paths must decide identically.
        """
        controller = build_run_command_controller(self.policy)
        executor = self._executor()
        battery = [
            "echo alix-parity-probe",
            "rm -rf / --no-preserve-root",
            "",
            "   ",
            "definitely_missing_alix_command_xyz",
        ]
        for cmd in battery:
            old = executor.run_command(cmd)
            new = controller.handle({"command": cmd})
            self.assertEqual(
                old["ok"], new["ok"],
                f"decision diverged for {cmd!r}: "
                f"executor={old['ok']} slice={new['ok']}",
            )


class TestRunCommandWiring(unittest.TestCase):
    def test_bridge_exposes_run_command(self):
        from core.feature_bridge import build_migrated_tool_handlers

        handlers = build_migrated_tool_handlers(Policy())
        self.assertIn("run_command", handlers)

    def test_controller_handle_accepts_missing_arguments(self):
        controller = build_run_command_controller(Policy())
        result = controller.handle(None)
        self.assertFalse(result["ok"])
        result = controller.handle({})
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
