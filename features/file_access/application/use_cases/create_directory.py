"""Create-directory use case: validate -> authorize -> run."""
from __future__ import annotations

import time

from features.file_access.application.dto.create_directory import (
    CreateDirectoryRequest,
)
from features.file_access.application.ports.directory_authorization import (
    DirectoryAuthorizationPort,
)
from features.file_access.application.ports.directory_runner import (
    DirectoryRunnerPort,
)


class CreateDirectoryUseCase:
    """Application service for the create_directory tool."""

    def __init__(
        self,
        authorization: DirectoryAuthorizationPort,
        runner: DirectoryRunnerPort,
    ):
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: CreateDirectoryRequest) -> dict:
        started = time.monotonic()

        if not isinstance(request.path, str) or not request.path.strip():
            return self._deny(started, "مسار المجلد غير صالح.")

        # Authorization is checked before the runner is touched at all --
        # mirrors WriteFileUseCase: the runner double in the tests raises
        # if it is ever called for an unauthorized path.
        if not self._authorization.can_create_directory(request.path):
            return self._deny(started, "غير مصرَّح بإنشاء هذا المجلد.")

        return self._runner.run_create_directory(request.path)

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # Full ExecutionResult shape per SCHEMA_CONTRACT.md.
        return {
            "ok": False,
            "action": "create_directory",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
