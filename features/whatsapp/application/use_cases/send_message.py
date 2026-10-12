"""Send a WhatsApp message; authorization is checked before the gateway."""
from __future__ import annotations

from typing import Any

from features.whatsapp.application.dto.whatsapp import SendWhatsAppRequest


class SendWhatsAppUseCase:
    def __init__(self, authorization: Any, gateway: Any) -> None:
        self._authorization = authorization
        self._gateway = gateway

    def execute(self, request: SendWhatsAppRequest) -> dict:
        if not self._authorization.can_send():
            return {
                "ok": False,
                "action": "whatsapp_send",
                "message": "مرفوضة بواسطة السياسة.",
                "evidence": {},
            }
        return self._gateway.send_text(request.to, request.text)
