from __future__ import annotations

from typing import Any

from features.web.application.dto.web_search import WebSearchRequest


class WebSearchController:
    """Builds a WebSearchRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = WebSearchRequest(
            query=str(arguments.get("query", "")),
            max_results=_coerce_int(arguments.get("max_results", 5), 5),
        )
        return self._use_case.execute(request)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
