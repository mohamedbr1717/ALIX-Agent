from __future__ import annotations

from typing import Any

from features.file_access.application.dto.write_file import WriteFileRequest
from features.file_access.application.use_cases.write_file import WriteFileUseCase


class WriteFileController:
    def __init__(self, use_case: WriteFileUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}

        request = WriteFileRequest(
            path=arguments.get("path", ""),
            content=arguments.get("content", ""),
        )

        return self._use_case.execute(request)
