from __future__ import annotations

from typing import Protocol


class SearchRunner(Protocol):
    """Executes the search and returns the result dict."""

    def run_search(self, pattern: str, path: str, max_matches: int) -> dict: ...
