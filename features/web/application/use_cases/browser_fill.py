from __future__ import annotations

from typing import Any

from features.web.application.dto.browser_fill import BrowserFillRequest


class BrowserFillUseCase:
    """Fill form fields (no submit); authorization checked first."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: BrowserFillRequest) -> dict:
        if not self._authorization.can_browse(request.url):
            return {
                "ok": False,
                "action": "browser_fill",
                "message": "Browse not authorized: URL rejected.",
                "evidence": {},
            }
        if not request.fields:
            return {
                "ok": False,
                "action": "browser_fill",
                "message": "No fields provided.",
                "evidence": {},
            }
        result = self._runner.fill_fields(request.url, request.fields)
        result["action"] = "browser_fill"
        return result
