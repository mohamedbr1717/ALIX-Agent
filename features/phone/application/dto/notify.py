from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotifyRequest:
    """Request to show a phone notification via Termux:API."""

    title: str
    content: str
