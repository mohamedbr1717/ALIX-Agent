from __future__ import annotations

from typing import Protocol


class FactAuthorization(Protocol):
    """Decides whether a fact may be remembered (deny-before-runner)."""

    def can_remember(self, fact: str) -> bool: ...
