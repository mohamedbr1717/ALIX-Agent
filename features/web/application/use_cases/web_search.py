from __future__ import annotations

from typing import Any

from features.web.application.dto.web_search import WebSearchRequest


class WebSearchUseCase:
    """Web search; authorization is checked before the runner."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: WebSearchRequest) -> dict:
        if not self._authorization.can_search(request.query):
            return {
                "ok": False,
                "action": "web_search",
                "message": "Search not authorized: empty query.",
                "evidence": {},
            }
        return self._runner.run_search(request.query, request.max_results)
