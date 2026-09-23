from __future__ import annotations

from typing import Protocol


class WebSearchAuthorization(Protocol):
    """Decides whether a web search may run (deny-before-runner)."""

    def can_search(self, query: str) -> bool: ...
