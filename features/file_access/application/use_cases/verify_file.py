from __future__ import annotations

from typing import Any

from features.file_access.application.dto.verify_file import VerifyFileRequest


class VerifyFileUseCase:
    """File verification; authorization is checked before the runner."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: VerifyFileRequest) -> dict:
        if not self._authorization.can_verify(request.path):
            return {
                "ok": False,
                "action": "verify_file",
                "message": "المسار غير مسموح.",
                "evidence": {},
            }
        return self._runner.run_verification(request.path)
