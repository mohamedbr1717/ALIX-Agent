"""Controller (interface adapter) for the create_directory tool."""
from __future__ import annotations

from features.file_access.application.dto.create_directory import (
    CreateDirectoryRequest,
)
from features.file_access.application.use_cases.create_directory import (
    CreateDirectoryUseCase,
)


class CreateDirectoryController:
    """Translate raw tool arguments into a use-case request."""

    def __init__(self, use_case: CreateDirectoryUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = CreateDirectoryRequest(
            path=arguments.get("path", ""),
        )
        return self._use_case.execute(request)
