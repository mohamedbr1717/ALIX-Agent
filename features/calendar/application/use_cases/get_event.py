"""Get one calendar event by id use case (Decision 2)."""

from __future__ import annotations

from typing import Any

from features.calendar.application.dto.calendar import (
    CalendarResult,
    GetEventRequest,
)


class GetEventUseCase:
    """Read a single event back — the verification channel for
    calendar_add / calendar_delete effects. Read-only."""

    def __init__(self, gateway: Any):
        self._gateway = gateway

    def execute(self, request: GetEventRequest) -> CalendarResult:
        event_id = request.event_id.strip()
        if not event_id:
            return CalendarResult(
                ok=False, message="معرف الموعد مطلوب للقراءة."
            )
        result = self._gateway.get_event(event_id)
        if not result.get("ok"):
            return CalendarResult(
                ok=False,
                message=(
                    "تعذّرت قراءة الموعد: "
                    f"{result.get('error', 'خطأ غير معروف')}"
                ),
            )
        if not result.get("found"):
            return CalendarResult(
                ok=True,
                message="الموعد غير موجود.",
                found=False,
            )
        return CalendarResult(
            ok=True,
            message="تمّت قراءة الموعد.",
            found=True,
            event=result.get("event"),
        )
