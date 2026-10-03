from __future__ import annotations

from typing import Any

from features.phone.application.dto.notify import NotifyRequest
from features.phone.application.dto.phone_call import PhoneCallRequest
from features.phone.application.dto.send_sms import SendSmsRequest


class PhoneCallController:
    """Builds a PhoneCallRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = PhoneCallRequest(
            number=str(arguments.get("number", "")).strip(),
        )
        return self._use_case.execute(request)


class SendSmsController:
    """Builds a SendSmsRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = SendSmsRequest(
            number=str(arguments.get("number", "")).strip(),
            message=str(arguments.get("message", "")),
        )
        return self._use_case.execute(request)


class NotifyController:
    """Builds a NotifyRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = NotifyRequest(
            title=str(arguments.get("title", "") or "ALIX").strip(),
            content=str(arguments.get("content", "")),
        )
        return self._use_case.execute(request)
