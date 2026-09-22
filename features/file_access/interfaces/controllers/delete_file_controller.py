from __future__ import annotations

from typing import Any

from features.file_access.application.dto.delete_file import DeleteFileRequest
from features.file_access.application.use_cases.delete_file import (
    DeleteFileUseCase,
)


class DeleteFileController:
    def __init__(self, use_case: DeleteFileUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}

        request = DeleteFileRequest(
            path=arguments.get("path", ""),
        )

        return self._use_case.execute(request)
