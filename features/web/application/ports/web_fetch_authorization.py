from __future__ import annotations

from typing import Protocol


class WebFetchAuthorization(Protocol):
    """Decides whether a URL may be fetched (deny-before-runner)."""

    def can_fetch(self, url: str) -> bool: ...
