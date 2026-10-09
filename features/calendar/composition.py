"""Composition root for the calendar feature slice."""

from __future__ import annotations

from typing import Any

from features.calendar.application.use_cases.add_event import AddEventUseCase
from features.calendar.application.use_cases.delete_event import (
    DeleteEventUseCase,
)
from features.calendar.application.use_cases.list_events import (
    ListEventsUseCase,
)
from features.calendar.infrastructure.adapters.google_calendar_gateway import (
    GoogleCalendarGateway,
)
from features.calendar.interfaces.controllers.calendar_controller import (
    AddEventController,
    DeleteEventController,
    ListEventsController,
)


def build_calendar_controllers(
    policy: Any,
) -> dict[str, Any]:
    """Build the three calendar controllers sharing one gateway."""
    gateway = GoogleCalendarGateway()
    return {
        "calendar_list": ListEventsController(
            ListEventsUseCase(gateway=gateway)
        ),
        "calendar_add": AddEventController(
            AddEventUseCase(gateway=gateway)
        ),
        "calendar_delete": DeleteEventController(
            DeleteEventUseCase(gateway=gateway)
        ),
    }
