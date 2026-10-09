from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolveContactRequest:
    """Request to resolve a contact name to a phone number."""

    name: str
