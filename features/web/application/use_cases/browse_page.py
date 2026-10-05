from __future__ import annotations

from typing import Any

from features.web.application.dto.browse_page import BrowsePageRequest


class BrowsePageUseCase:
    """Load a page and extract text; authorization checked first."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: BrowsePageRequest) -> dict:
        if not self._authorization.can_browse(request.url):
            return {
                "ok": False,
                "action": "browse_page",
                "message": "Browse not authorized: URL rejected.",
                "evidence": {},
            }
        result = self._runner.load_page_text(request.url, request.max_chars)
        result["action"] = "browse_page"
        return result
