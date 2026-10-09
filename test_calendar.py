"""Behavioral tests for the calendar feature slice.

Tests use a fake gateway (no network, no Google credentials).
"""

import os
import unittest
from unittest.mock import patch

from features.calendar.application.dto.calendar import (
    AddEventRequest,
    DeleteEventRequest,
    ListEventsRequest,
)
from features.calendar.application.use_cases.add_event import AddEventUseCase
from features.calendar.application.use_cases.delete_event import (
    DeleteEventUseCase,
)
from features.calendar.application.use_cases.list_events import (
    ListEventsUseCase,
)
from features.calendar.composition import build_calendar_controllers
from features.calendar.domain.event import CalendarEvent
from features.calendar.infrastructure.adapters.google_calendar_gateway import (
    GoogleCalendarGateway,
)


class FakeGateway:
    """In-memory fake implementing the CalendarGateway port."""

    def __init__(self):
        self.events = []
        self._next_id = 1

    def list_events(self, time_min, time_max, max_results):
        return {"ok": True, "events": self.events[:max_results]}

    def add_event(self, event):
        event_id = f"evt-{self._next_id}"
        self._next_id += 1
        self.events.append({**event, "event_id": event_id})
        return {"ok": True, "event_id": event_id}

    def delete_event(self, event_id):
        before = len(self.events)
        self.events = [
            e for e in self.events if e.get("event_id") != event_id
        ]
        if len(self.events) == before:
            return {"ok": False, "error": "not found"}
        return {"ok": True}


class TestCalendarDomain(unittest.TestCase):
    def test_event_valid(self):
        e = CalendarEvent(
            title="اجتماع", start="2026-10-10T10:00:00+01:00", end="2026-10-10T11:00:00+01:00"
        )
        self.assertTrue(e.is_valid())

    def test_event_invalid_empty_title(self):
        e = CalendarEvent(title="  ", start="2026-10-10T10:00:00+01:00", end="")
        self.assertFalse(e.is_valid())


class TestCalendarUseCases(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()

    def test_list_empty(self):
        uc = ListEventsUseCase(gateway=self.gateway)
        result = uc.execute(
            ListEventsRequest(time_min="2026-10-10T00:00:00+01:00", time_max="2026-10-11T00:00:00+01:00")
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.events, [])

    def test_list_missing_range(self):
        uc = ListEventsUseCase(gateway=self.gateway)
        result = uc.execute(ListEventsRequest(time_min="", time_max=""))
        self.assertFalse(result.ok)

    def test_add_and_list(self):
        add = AddEventUseCase(gateway=self.gateway)
        result = add.execute(
            AddEventRequest(
                title="موعد طبيب",
                start="2026-10-10T15:00:00+01:00",
                end="2026-10-10T16:00:00+01:00",
            )
        )
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.event_id)

        lst = ListEventsUseCase(gateway=self.gateway)
        listed = lst.execute(
            ListEventsRequest(time_min="2026-10-10T00:00:00+01:00", time_max="2026-10-11T00:00:00+01:00")
        )
        self.assertTrue(listed.ok)
        self.assertEqual(len(listed.events), 1)

    def test_add_invalid(self):
        add = AddEventUseCase(gateway=self.gateway)
        result = add.execute(
            AddEventRequest(title="", start="", end="")
        )
        self.assertFalse(result.ok)

    def test_delete(self):
        add = AddEventUseCase(gateway=self.gateway)
        created = add.execute(
            AddEventRequest(
                title="للحذف",
                start="2026-10-10T15:00:00+01:00",
                end="2026-10-10T16:00:00+01:00",
            )
        )
        delete = DeleteEventUseCase(gateway=self.gateway)
        result = delete.execute(
            DeleteEventRequest(event_id=created.event_id)
        )
        self.assertTrue(result.ok)

    def test_delete_missing_id(self):
        delete = DeleteEventUseCase(gateway=self.gateway)
        result = delete.execute(DeleteEventRequest(event_id=""))
        self.assertFalse(result.ok)

    def test_delete_nonexistent(self):
        delete = DeleteEventUseCase(gateway=self.gateway)
        result = delete.execute(DeleteEventRequest(event_id="nope"))
        self.assertFalse(result.ok)


class TestCalendarGatewayFailClosed(unittest.TestCase):
    """Gateway without credentials must fail closed, never raise."""

    def test_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            gw = GoogleCalendarGateway()
            self.assertFalse(gw.is_configured())
            result = gw.list_events("2026-10-10T00:00:00+01:00", "2026-10-11T00:00:00+01:00", 10)
            self.assertFalse(result["ok"])
            self.assertIn("error", result)


class TestCalendarComposition(unittest.TestCase):
    def test_build_controllers(self):
        controllers = build_calendar_controllers(policy=None)
        self.assertIn("calendar_list", controllers)
        self.assertIn("calendar_add", controllers)
        self.assertIn("calendar_delete", controllers)


if __name__ == "__main__":
    unittest.main()
