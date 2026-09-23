"""List-files use case: authorize -> run."""
from __future__ import annotations

import time

from features.file_access.application.dto.list_files import (
    ListFilesRequest,
)
from features.file_access.application.ports.file_listing_authorization import (
    FileListingAuthorizationPort,
)
from features.file_access.application.ports.file_listing_runner import (
    FileListingRunnerPort,
)


class ListFilesUseCase:
    """Application service for the list_files tool (read-only)."""

    def __init__(
        self,
        authorization: FileListingAuthorizationPort,
        runner: FileListingRunnerPort,
    ):
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: ListFilesRequest) -> dict:
        started = time.monotonic()

        # Read-only but still workspace-scoped: deny before the runner is
        # touched at all. The runner re-checks fail-closed (defense in
        # depth); the message mirrors the canonical implementation's.
        if not self._authorization.can_list_files(request.path):
            return self._deny(started, "المسار خارج مساحة ALIX.")

        return self._runner.run_list_files(request.path, request.all)

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # Full ExecutionResult shape per SCHEMA_CONTRACT.md.
        return {
            "ok": False,
            "action": "list_files",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
