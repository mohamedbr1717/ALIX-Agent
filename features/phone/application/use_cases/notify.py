from __future__ import annotations

from typing import Any

from features.phone.application.dto.notify import NotifyRequest


class NotifyUseCase:
    """Show a phone notification; authorization is checked first."""

    def __init__(self, authorization: Any, gateway: Any) -> None:
        self._authorization = authorization
        self._gateway = gateway

    def execute(self, request: NotifyRequest) -> dict:
        if not self._authorization.can_notify():
            return {
                "ok": False,
                "action": "notify",
                "message": "مرفوضة بواسطة السياسة.",
                "evidence": {},
            }
        return self._gateway.notify(request.title, request.content)
