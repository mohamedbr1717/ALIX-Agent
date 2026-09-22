from __future__ import annotations

import time

from features.command_execution.application.dto.run_command import (
    RunCommandRequest,
)
from features.command_execution.application.ports.command_authorization import (
    CommandAuthorizationPort,
)
from features.command_execution.application.ports.command_runner import (
    CommandRunnerPort,
)


class RunCommandUseCase:
    def __init__(
        self,
        runner: CommandRunnerPort,
        authorization: CommandAuthorizationPort,
    ):
        self._runner = runner
        self._authorization = authorization

    def execute(self, request: RunCommandRequest) -> dict:
        started = time.monotonic()

        if not isinstance(request.command, str) or not request.command.strip():
            return self._deny(started, "الأمر غير صالح.")

        # Authorization is checked before the runner is touched at all --
        # mirrors DeleteFileUseCase: the runner double test below proves
        # this by raising if ever called on a denied command.
        if not self._authorization.can_run_command(request.command):
            return self._deny(started, "غير مصرَّح بتنفيذ هذا الأمر.")

        return self._runner.run_command(
            command=request.command,
        )

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # SCHEMA FIX: matches the canonical ExecutionResult contract
        # documented in SCHEMA_CONTRACT.md -- every early-rejection
        # path must return this full shape.
        return {
            "ok": False,
            "action": "run_command",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
