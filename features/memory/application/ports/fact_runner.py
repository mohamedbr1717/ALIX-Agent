from __future__ import annotations

from typing import Protocol


class FactRunner(Protocol):
    """Persists the fact/preference and returns the result dict."""

    def run_remember(self, fact: str, is_preference: bool) -> dict: ...
