from __future__ import annotations

from typing import Any

from features.file_access.application.dto.search_files import SearchFilesRequest


class SearchFilesUseCase:
    """Search for a pattern; authorization is checked before the runner."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: SearchFilesRequest) -> dict:
        if not self._authorization.can_search_files(
            request.pattern, request.path
        ):
            return {
                "ok": False,
                "action": "search_files",
                "message": "Search not authorized: invalid pattern or path.",
                "evidence": {},
            }
        return self._runner.run_search(
            request.pattern, request.path, request.max_matches
        )
