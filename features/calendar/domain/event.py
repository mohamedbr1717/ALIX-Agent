"""Calendar event domain entity (pure, no infrastructure)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalendarEvent:
    """A calendar event.

    start/end are ISO-8601 strings with timezone offset.
    event_id is the provider's identifier (None for new events).
    """

    title: str
    start: str
    end: str
    description: str = ""
    event_id: str | None = None

    def is_valid(self) -> bool:
        return bool(self.title.strip()) and bool(self.start.strip())
