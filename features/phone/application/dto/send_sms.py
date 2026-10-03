from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SendSmsRequest:
    """Request to send an SMS via Termux:API."""

    number: str
    message: str
