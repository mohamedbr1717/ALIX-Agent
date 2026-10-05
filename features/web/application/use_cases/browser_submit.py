from __future__ import annotations

from typing import Any

from features.web.application.dto.browser_submit import BrowserSubmitRequest


class BrowserSubmitUseCase:
    """Final submit/click — destructive; authorization checked first."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: BrowserSubmitRequest) -> dict:
        if not self._authorization.can_browse(request.url):
            return {
                "ok": False,
                "action": "browser_submit",
                "message": "Browse not authorized: URL rejected.",
                "evidence": {},
            }
        if not request.selector:
            return {
                "ok": False,
                "action": "browser_submit",
                "message": "No selector provided.",
                "evidence": {},
            }
        result = self._runner.click_submit(request.url, request.selector)
        result["action"] = "browser_submit"
        return result
