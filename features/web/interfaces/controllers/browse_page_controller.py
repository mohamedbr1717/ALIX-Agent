from __future__ import annotations

from typing import Any

from features.web.application.dto.browse_page import BrowsePageRequest


class BrowsePageController:
    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = BrowsePageRequest(
            url=str(arguments.get("url", "")),
            max_chars=_coerce_int(arguments.get("max_chars", 8000), 8000),
        )
        return self._use_case.execute(request)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
