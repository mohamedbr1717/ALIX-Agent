"""Calendar DTOs (application layer contracts)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ListEventsRequest:
    time_min: str  # ISO-8601
    time_max: str  # ISO-8601
    max_results: int = 20


@dataclass(frozen=True)
class AddEventRequest:
    title: str
    start: str  # ISO-8601 with offset
    end: str  # ISO-8601 with offset
    description: str = ""
    timezone: str = "Africa/Casablanca"


@dataclass(frozen=True)
class DeleteEventRequest:
    event_id: str


@dataclass(frozen=True)
class GetEventRequest:
    event_id: str


@dataclass(frozen=True)
class CalendarResult:
    ok: bool
    message: str
    events: list = field(default_factory=list)
    event_id: str | None = None
    #: Decision 2 (calendar_get only): whether the read found the
    #: event, and the event itself when it did.
    found: bool | None = None
    event: dict | None = None
