"""Add calendar event use case."""

from __future__ import annotations

from typing import Any

from features.calendar.application.dto.calendar import (
    AddEventRequest,
    CalendarResult,
)
from features.calendar.domain.event import CalendarEvent


class AddEventUseCase:
    """Create a calendar event (reversible → execute level, not destructive)."""

    def __init__(self, gateway: Any):
        self._gateway = gateway

    def execute(self, request: AddEventRequest) -> CalendarResult:
        event = CalendarEvent(
            title=request.title.strip(),
            start=request.start.strip(),
            end=request.end.strip(),
            description=request.description.strip(),
        )
        if not event.is_valid():
            return CalendarResult(
                ok=False,
                message="العنوان ووقت البدء مطلوبان.",
            )
        result = self._gateway.add_event(
            {
                "title": event.title,
                "start": event.start,
                "end": event.end,
                "description": event.description,
                "timezone": request.timezone,
            }
        )
        if not result.get("ok"):
            return CalendarResult(
                ok=False,
                message=f"تعذر إنشاء الموعد: {result.get('error', 'خطأ غير معروف')}",
            )
        return CalendarResult(
            ok=True,
            message=f"تم إنشاء الموعد «{event.title}».",
            event_id=result.get("event_id"),
        )
