"""Runner adapter that delegates to the hardened SafeExecutor."""
from __future__ import annotations

from typing import Any

from features.system.application.ports.system_runner import SystemRunnerPort


class ExecutorSystemRunnerAdapter(SystemRunnerPort):
    """Delegate to SafeExecutor.system_info / git_read_only.

    All hardening is preserved by delegation: no shell, per-command
    policy gates, bounded subprocesses, output truncation, and the
    read-only git allowlist.
    """

    def __init__(self, policy: Any):
        self._policy = policy

    def run_system_info(self) -> dict:
        # Deferred import: core.feature_bridge imports this composition at
        # call time, so a module-level core import could cycle.
        from core.executor import SafeExecutor

        return SafeExecutor(self._policy).system_info()

    def run_git_status(self, action: str) -> dict:
        from core.executor import SafeExecutor

        return SafeExecutor(self._policy).git_read_only(action)
