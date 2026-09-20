from __future__ import annotations

import time

from features.file_access.application.dto.read_file import ReadFileRequest
from features.file_access.application.ports.authorization import (
    AuthorizationPort,
)
from features.file_access.application.ports.file_storage import (
    FileStoragePort,
)


class ReadFileUseCase:
    def __init__(
        self,
        storage: FileStoragePort,
        authorization: AuthorizationPort,
    ):
        self._storage = storage
        self._authorization = authorization

    def execute(self, request: ReadFileRequest) -> dict:
        started = time.monotonic()

        if not isinstance(request.path, str) or not request.path.strip():
            return self._deny(started, "مسار الملف غير صالح.")

        # Authorization is checked before storage is touched at all --
        # see TestReadFileAuthorizationBoundary, which proves this
        # with a storage double that raises if ever called.
        if not self._authorization.can_read_file(request.path):
            return self._deny(started, "غير مصرَّح بقراءة هذا الملف.")

        try:
            start_line = max(1, int(request.start_line))
            end_line = (
                None
                if request.end_line is None
                else max(start_line, int(request.end_line))
            )
        except (TypeError, ValueError):
            return self._deny(started, "معاملات قراءة الملف غير صالحة.")

        return self._storage.read_file(
            path=request.path,
            start_line=start_line,
            end_line=end_line,
            max_output=request.normalized_max_output(),
        )

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # SCHEMA FIX: matches the canonical ExecutionResult contract
        # documented in SCHEMA_CONTRACT.md -- see that file for why
        # every early-rejection path across the codebase must return
        # this full shape, not a bare {"ok", "action", "message"}.
        return {
            "ok": False,
            "action": "read_file",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
