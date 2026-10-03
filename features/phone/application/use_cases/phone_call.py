from __future__ import annotations

from typing import Any

from features.phone.application.dto.phone_call import PhoneCallRequest


class PhoneCallUseCase:
    """Place a phone call; authorization is checked before the gateway."""

    def __init__(self, authorization: Any, gateway: Any) -> None:
        self._authorization = authorization
        self._gateway = gateway

    def execute(self, request: PhoneCallRequest) -> dict:
        if not self._authorization.can_call(request.number):
            return {
                "ok": False,
                "action": "phone_call",
                "message": "مرفوضة بواسطة السياسة.",
                "evidence": {},
            }
        return self._gateway.place_call(request.number)
