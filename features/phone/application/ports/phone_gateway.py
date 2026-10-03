from __future__ import annotations

from typing import Protocol


class PhoneGateway(Protocol):
    """Executes phone actions. Implementations must never use a shell."""

    def place_call(self, number: str) -> dict: ...
    def send_sms(self, number: str, message: str) -> dict: ...
    def notify(self, title: str, content: str) -> dict: ...
