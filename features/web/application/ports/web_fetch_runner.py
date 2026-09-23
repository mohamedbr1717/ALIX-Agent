from __future__ import annotations

from typing import Protocol


class WebFetchRunner(Protocol):
    """Fetches a URL and returns the result dict."""

    def run_fetch(self, url: str, max_chars: int) -> dict: ...
