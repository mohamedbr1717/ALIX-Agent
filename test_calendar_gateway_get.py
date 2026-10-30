"""Behavioral tests for calendar_get (Decision 2's read channel).

The distinction these tests pin down is the one verification is
built on: "proven absent" (provider answered 404/410 → ok=True,
found=False) must never be confused with "could not read"
(provider failed → ok=False, no found claim). Field mapping
mirrors list_events: summary → title, start/end dateTime (or
date for all-day events).
"""
from __future__ import annotations

import unittest

from features.calendar.application.dto.calendar import (
    GetEventRequest,
)
from features.calendar.application.use_cases.get_event import (
    GetEventUseCase,
)
from features.calendar.infrastructure.adapters.google_calendar_gateway import (
    GoogleCalendarGateway,
)
from features.calendar.interfaces.controllers.calendar_controller import (
    GetEventController,
)


def _gateway(responder):
    gateway = object.__new__(GoogleCalendarGateway)
    calls = []

    def fake_request(method, path, body=None):
        calls.append((method, path))
        return responder(method, path)

    gateway._request = fake_request
    return gateway, calls


def _found_item(method, path):
    return {
        "ok": True,
        "data": {
            "id": "evt-1",
            "summary": "مكالمة مع سعاد",
            "description": "متابعة",
            "start": {"dateTime": "2026-10-30T10:00:00Z"},
            "end": {"dateTime": "2026-10-30T11:00:00Z"},
        },
    }


class TestGatewayGetEvent(unittest.TestCase):
    def test_found_event_maps_fields(self):
        gateway, calls = _gateway(_found_item)
        result = gateway.get_event("evt-1")
        self.assertTrue(result["ok"])
        self.assertTrue(result["found"])
        self.assertEqual(result["event"]["event_id"], "evt-1")
        self.assertEqual(result["event"]["title"], "مكالمة مع سعاد")
        self.assertEqual(
            result["event"]["start"], "2026-10-30T10:00:00Z"
        )
        self.assertEqual(calls[0][0], "GET")
        self.assertIn("/events/evt-1", calls[0][1])

    def test_event_id_is_url_quoted(self):
        gateway, calls = _gateway(_found_item)
        gateway.get_event("a/b c")
        self.assertIn("/events/a%2Fb%20c", calls[0][1])

    def test_404_is_proven_absent(self):
        gateway, _ = _gateway(
            lambda m, p: {"ok": False, "error": "HTTP 404"}
        )
        result = gateway.get_event("gone")
        self.assertEqual(result, {"ok": True, "found": False})

    def test_410_is_proven_absent(self):
        gateway, _ = _gateway(
            lambda m, p: {"ok": False, "error": "HTTP 410"}
        )
        result = gateway.get_event("gone")
        self.assertEqual(result, {"ok": True, "found": False})

    def test_500_is_unreadable_not_absent(self):
        gateway, _ = _gateway(
            lambda m, p: {"ok": False, "error": "HTTP 500"}
        )
        result = gateway.get_event("evt-1")
        self.assertFalse(result["ok"])
        self.assertNotIn("found", result)

    def test_cancelled_tombstone_is_absent(self):
        # Google answers a deleted event's GET with 200 and
        # status "cancelled" (live-proven 2026-10-30). Absent is
        # absent: the read-back must not report it as found.
        def cancelled(method, path):
            return {
                "ok": True,
                "data": {
                    "id": "evt-1",
                    "status": "cancelled",
                    "summary": "اجتماع اختبار التحقق",
                    "start": {"dateTime": "2026-11-02T09:00:00Z"},
                    "end": {"dateTime": "2026-11-02T10:00:00Z"},
                },
            }

        gateway, _ = _gateway(cancelled)
        result = gateway.get_event("evt-1")
        self.assertEqual(result, {"ok": True, "found": False})


class _FakeGateway:
    def __init__(self, result):
        self.result = result

    def get_event(self, event_id):
        return self.result


class TestGetEventUseCaseAndController(unittest.TestCase):
    def test_empty_id_rejected_without_gateway_call(self):
        use_case = GetEventUseCase(gateway=_FakeGateway({"ok": True}))
        result = use_case.execute(GetEventRequest(event_id="  "))
        self.assertFalse(result.ok)

    def test_controller_payload_carries_found_and_event(self):
        gateway = _FakeGateway(
            {
                "ok": True,
                "found": True,
                "event": {"event_id": "e1", "title": "t"},
            }
        )
        controller = GetEventController(GetEventUseCase(gateway))
        payload = controller.handle({"event_id": "e1"})
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["found"])
        self.assertEqual(payload["event"]["title"], "t")

    def test_controller_payload_marks_absence_explicitly(self):
        gateway = _FakeGateway({"ok": True, "found": False})
        controller = GetEventController(GetEventUseCase(gateway))
        payload = controller.handle({"event_id": "gone"})
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["found"])
        self.assertNotIn("event", payload)

    def test_gateway_error_surfaces_as_not_ok(self):
        gateway = _FakeGateway(
            {"ok": False, "error": "HTTP 500"}
        )
        controller = GetEventController(GetEventUseCase(gateway))
        payload = controller.handle({"event_id": "e1"})
        self.assertFalse(payload["ok"])
        self.assertNotIn("found", payload)


if __name__ == "__main__":
    unittest.main()
