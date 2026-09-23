from __future__ import annotations

from typing import Any

from features.web.application.dto.web_fetch import WebFetchRequest


class WebFetchUseCase:
    """URL fetch; authorization (SSRF guard) is checked before the runner."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: WebFetchRequest) -> dict:
        if not self._authorization.can_fetch(request.url):
            return {
                "ok": False,
                "action": "web_fetch",
                "message": "Fetch not authorized: URL rejected.",
                "evidence": {},
            }
        return self._runner.run_fetch(request.url, request.max_chars)
