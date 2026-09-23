from __future__ import annotations

from typing import Protocol


class WebSearchRunner(Protocol):
    """Executes the web search and returns the result dict."""

    def run_search(self, query: str, max_results: int) -> dict: ...
