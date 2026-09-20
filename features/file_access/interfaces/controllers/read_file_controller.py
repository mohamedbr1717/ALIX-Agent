from __future__ import annotations

from typing import Any

from features.file_access.application.dto.read_file import ReadFileRequest
from features.file_access.application.use_cases.read_file import ReadFileUseCase


class ReadFileController:
    def __init__(self, use_case: ReadFileUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}

        request = ReadFileRequest(
            path=arguments.get("path", ""),
            start_line=arguments.get("start_line", 1),
            end_line=arguments.get("end_line"),
            max_output=arguments.get("max_output", 4000),
        )

        return self._use_case.execute(request)
