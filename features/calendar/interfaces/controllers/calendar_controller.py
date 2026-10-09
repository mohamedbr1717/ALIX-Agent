"""Calendar controllers (interface adapters)."""

from __future__ import annotations

from typing import Any

from features.calendar.application.dto.calendar import (
    AddEventRequest,
    DeleteEventRequest,
    ListEventsRequest,
)


class _BaseCalendarController:
    def __init__(self, use_case: Any):
        self._use_case = use_case

    @staticmethod
    def _result_dict(result: Any) -> dict:
        payload = {
            "ok": result.ok,
            "message": result.message,
        }
        if result.events:
            payload["events"] = result.events
        if result.event_id:
            payload["event_id"] = result.event_id
        return payload


class ListEventsController(_BaseCalendarController):
    """calendar_list tool handler."""

    def handle(self, arguments: dict) -> dict:
        request = ListEventsRequest(
            time_min=str(arguments.get("time_min", "")),
            time_max=str(arguments.get("time_max", "")),
            max_results=int(arguments.get("max_results", 20) or 20),
        )
        return self._result_dict(self._use_case.execute(request))


class AddEventController(_BaseCalendarController):
    """calendar_add tool handler."""

    def handle(self, arguments: dict) -> dict:
        request = AddEventRequest(
            title=str(arguments.get("title", "")),
            start=str(arguments.get("start", "")),
            end=str(arguments.get("end", "")),
            description=str(arguments.get("description", "")),
            timezone=str(
                arguments.get("timezone", "Africa/Casablanca")
            ),
        )
        return self._result_dict(self._use_case.execute(request))


class DeleteEventController(_BaseCalendarController):
    """calendar_delete tool handler."""

    def handle(self, arguments: dict) -> dict:
        request = DeleteEventRequest(
            event_id=str(arguments.get("event_id", ""))
        )
        return self._result_dict(self._use_case.execute(request))
