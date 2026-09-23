from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RememberFactRequest:
    """Request to persist a fact or preference in long-term memory."""

    fact: str
    is_preference: bool = False
