from __future__ import annotations

from typing import Any

from features.file_access.application.dto.verify_file import VerifyFileRequest


class VerifyFileController:
    """Builds a VerifyFileRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = VerifyFileRequest(path=str(arguments.get("path", "")))
        return self._use_case.execute(request)
