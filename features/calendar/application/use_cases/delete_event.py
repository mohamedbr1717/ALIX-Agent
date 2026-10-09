"""Delete calendar event use case."""

from __future__ import annotations

from typing import Any

from features.calendar.application.dto.calendar import (
    CalendarResult,
    DeleteEventRequest,
)


class DeleteEventUseCase:
    """Delete a calendar event (destructive → requires confirmation)."""

    def __init__(self, gateway: Any):
        self._gateway = gateway

    def execute(self, request: DeleteEventRequest) -> CalendarResult:
        event_id = request.event_id.strip()
        if not event_id:
            return CalendarResult(
                ok=False, message="معرف الموعد مطلوب للحذف."
            )
        result = self._gateway.delete_event(event_id)
        if not result.get("ok"):
            return CalendarResult(
                ok=False,
                message=f"تعذر حذف الموعد: {result.get('error', 'خطأ غير معروف')}",
            )
        return CalendarResult(ok=True, message="تم حذف الموعد.")
