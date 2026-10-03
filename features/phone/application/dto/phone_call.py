from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhoneCallRequest:
    """Request to place a phone call via Termux:API."""

    number: str
