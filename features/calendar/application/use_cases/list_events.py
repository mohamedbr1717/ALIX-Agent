"""List calendar events use case."""

from __future__ import annotations

from typing import Any

from features.calendar.application.dto.calendar import (
    CalendarResult,
    ListEventsRequest,
)


class ListEventsUseCase:
    """Read-only: list events in a time range."""

    def __init__(self, gateway: Any):
        self._gateway = gateway

    def execute(self, request: ListEventsRequest) -> CalendarResult:
        if not request.time_min or not request.time_max:
            return CalendarResult(
                ok=False,
                message="النطاق الزمني مطلوب (time_min و time_max).",
            )
        result = self._gateway.list_events(
            request.time_min,
            request.time_max,
            max(1, min(request.max_results, 50)),
        )
        if not result.get("ok"):
            return CalendarResult(
                ok=False,
                message=f"تعذر جلب المواعيد: {result.get('error', 'خطأ غير معروف')}",
            )
        events = result.get("events", [])
        if not events:
            return CalendarResult(
                ok=True, message="لا توجد مواعيد في هذا النطاق.", events=[]
            )
        return CalendarResult(
            ok=True,
            message=f"وجدت {len(events)} موعدًا.",
            events=events,
        )
