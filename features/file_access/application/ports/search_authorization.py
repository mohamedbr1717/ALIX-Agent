from __future__ import annotations

from typing import Protocol


class SearchAuthorization(Protocol):
    """Decides whether a search may run (deny-before-runner)."""

    def can_search_files(self, pattern: str, path: str) -> bool: ...
