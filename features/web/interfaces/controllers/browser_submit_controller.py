from __future__ import annotations

from typing import Any

from features.web.application.dto.browser_submit import BrowserSubmitRequest


class BrowserSubmitController:
    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = BrowserSubmitRequest(
            url=str(arguments.get("url", "")),
            selector=str(arguments.get("selector", "")),
            description=str(arguments.get("description", "")),
        )
        return self._use_case.execute(request)
