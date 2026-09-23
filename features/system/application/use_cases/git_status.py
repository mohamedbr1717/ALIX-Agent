"""git_status use case: validate -> authorize -> run."""
from __future__ import annotations

import time

from features.system.application.dto.git_status import GitStatusRequest
from features.system.application.ports.system_authorization import (
    SystemAuthorizationPort,
)
from features.system.application.ports.system_runner import SystemRunnerPort


class GitStatusUseCase:
    """Application service for the git_status tool (read-only git)."""

    def __init__(
        self,
        authorization: SystemAuthorizationPort,
        runner: SystemRunnerPort,
    ):
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: GitStatusRequest) -> dict:
        started = time.monotonic()

        action = request.action
        if not isinstance(action, str) or not action.strip():
            return self._deny(started, "إجراء Git غير صالح.")

        # Same allowlist SafeExecutor.git_read_only() enforces; denying
        # here keeps a disallowed action from reaching the runner at all.
        # The executor re-checks anyway (defense in depth).
        if not self._authorization.can_run_git(action):
            return self._deny(started, "عملية Git غير مسموحة.")

        return self._runner.run_git_status(action)

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # Full ExecutionResult shape per SCHEMA_CONTRACT.md.
        return {
            "ok": False,
            "action": "git_status",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
