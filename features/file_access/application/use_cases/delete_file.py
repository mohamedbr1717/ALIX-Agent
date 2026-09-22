from __future__ import annotations

import time

from features.file_access.application.dto.delete_file import DeleteFileRequest
from features.file_access.application.ports.authorization import (
    AuthorizationPort,
)
from features.file_access.application.ports.file_storage import (
    FileStoragePort,
)


class DeleteFileUseCase:
    def __init__(
        self,
        storage: FileStoragePort,
        authorization: AuthorizationPort,
    ):
        self._storage = storage
        self._authorization = authorization

    def execute(self, request: DeleteFileRequest) -> dict:
        started = time.monotonic()

        if not isinstance(request.path, str) or not request.path.strip():
            return self._deny(started, "مسار الملف غير صالح.")

        # Authorization is checked before storage is touched at all --
        # mirrors WriteFileUseCase: the storage double test below
        # proves this by raising if ever called on a denied path.
        if not self._authorization.can_delete_file(request.path):
            return self._deny(started, "غير مصرَّح بحذف هذا الملف.")

        return self._storage.delete_file(
            path=request.path,
        )

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # SCHEMA FIX: matches the canonical ExecutionResult contract
        # documented in SCHEMA_CONTRACT.md -- see that file for why
        # every early-rejection path across the codebase must return
        # this full shape, not a bare {"ok", "action", "message"}.
        return {
            "ok": False,
            "action": "delete_file",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
