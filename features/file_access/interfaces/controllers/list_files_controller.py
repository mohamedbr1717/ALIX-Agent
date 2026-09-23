"""Controller (interface adapter) for the list_files tool."""
from __future__ import annotations

from features.file_access.application.dto.list_files import (
    ListFilesRequest,
)
from features.file_access.application.use_cases.list_files import (
    ListFilesUseCase,
)


class ListFilesController:
    """Translate raw tool arguments into a use-case request."""

    def __init__(self, use_case: ListFilesUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = ListFilesRequest(
            path=arguments.get("path", "."),
            all=bool(arguments.get("all", False)),
        )
        return self._use_case.execute(request)
