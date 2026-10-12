"""Controller for the WhatsApp feature."""
from __future__ import annotations

from typing import Any

from features.whatsapp.application.dto.whatsapp import SendWhatsAppRequest


class SendWhatsAppController:
    """Builds a SendWhatsAppRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = SendWhatsAppRequest(
            to=str(arguments.get("to", "")).strip(),
            text=str(arguments.get("text", "")),
        )
        return self._use_case.execute(request)
