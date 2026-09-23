from __future__ import annotations

from typing import Any

from features.file_access.application.dto.search_files import SearchFilesRequest


class SearchFilesController:
    """Builds a SearchFilesRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = SearchFilesRequest(
            pattern=str(arguments.get("pattern", "")),
            path=str(arguments.get("path", ".")),
            max_matches=_coerce_max_matches(arguments.get("max_matches", 20)),
        )
        return self._use_case.execute(request)


def _coerce_max_matches(value: Any) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return 20
    return coerced if coerced >= 1 else 20
