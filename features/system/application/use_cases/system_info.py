"""system_info use case: authorize -> run."""
from __future__ import annotations

import time

from features.system.application.dto.system_info import SystemInfoRequest
from features.system.application.ports.system_authorization import (
    SystemAuthorizationPort,
)
from features.system.application.ports.system_runner import SystemRunnerPort


class SystemInfoUseCase:
    """Application service for the system_info tool (read-only)."""

    def __init__(
        self,
        authorization: SystemAuthorizationPort,
        runner: SystemRunnerPort,
    ):
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: SystemInfoRequest) -> dict:
        started = time.monotonic()

        if not self._authorization.can_collect_system_info():
            return self._deny(started, "غير مصرَّح بجمع معلومات النظام.")

        return self._runner.run_system_info()

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # Full ExecutionResult shape per SCHEMA_CONTRACT.md.
        return {
            "ok": False,
            "action": "system_info",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
