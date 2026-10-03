from __future__ import annotations

from typing import Any

from features.phone.application.dto.send_sms import SendSmsRequest


class SendSmsUseCase:
    """Send an SMS; authorization is checked before the gateway."""

    def __init__(self, authorization: Any, gateway: Any) -> None:
        self._authorization = authorization
        self._gateway = gateway

    def execute(self, request: SendSmsRequest) -> dict:
        if not self._authorization.can_text(request.number):
            return {
                "ok": False,
                "action": "send_sms",
                "message": "مرفوضة بواسطة السياسة.",
                "evidence": {},
            }
        return self._gateway.send_sms(request.number, request.message)
