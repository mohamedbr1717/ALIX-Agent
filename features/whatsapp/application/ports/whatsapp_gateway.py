"""Port for the WhatsApp Cloud API gateway (implemented in infrastructure)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class WhatsAppGateway(ABC):
    @abstractmethod
    def send_text(self, to: str, text: str) -> dict:
        """Send a text message. Returns a result dict with 'ok'."""
