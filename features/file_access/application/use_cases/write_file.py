from __future__ import annotations

import time

from features.file_access.application.dto.write_file import WriteFileRequest
from features.file_access.application.ports.authorization import (
    AuthorizationPort,
)
from features.file_access.application.ports.file_storage import (
    FileStoragePort,
)


class WriteFileUseCase:
    def __init__(
        self,
        storage: FileStoragePort,
        authorization: AuthorizationPort,
    ):
        self._storage = storage
        self._authorization = authorization

    def execute(self, request: WriteFileRequest) -> dict:
        started = time.monotonic()

        if not isinstance(request.path, str) or not request.path.strip():
            return self._deny(started, "مسار الملف غير صالح.")

        # Authorization is checked before storage is touched at all --
        # mirrors ReadFileUseCase: TestWriteFileAuthorizationBoundary
        # proves this with a storage double that raises if ever called.
        if not self._authorization.can_write_file(request.path):
            return self._deny(started, "غير مصرَّح بكتابة هذا الملف.")

        if not isinstance(request.content, str):
            return self._deny(started, "محتوى الملف يجب أن يكون نصًا.")

        return self._storage.write_file(
            path=request.path,
            content=request.content,
        )

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # SCHEMA FIX: matches the canonical ExecutionResult contract
        # documented in SCHEMA_CONTRACT.md -- see that file for why
        # every early-rejection path across the codebase must return
        # this full shape, not a bare {"ok", "action", "message"}.
        return {
            "ok": False,
            "action": "write_file",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
