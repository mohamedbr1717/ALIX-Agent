from __future__ import annotations

from typing import Any

from features.web.application.dto.browser_fill import BrowserFillRequest


class BrowserFillController:
    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        fields = arguments.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}
        request = BrowserFillRequest(
            url=str(arguments.get("url", "")),
            fields={str(k): v for k, v in fields.items()},
        )
        return self._use_case.execute(request)
