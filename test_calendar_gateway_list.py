"""Behavioral tests for GoogleCalendarGateway.list_events range handling.

Production failure these tests pin down (plan p_20261029T073726_3a37,
2026-10-29): the planner supplied naive datetimes
("2026-10-29T23:58:00") as time_min/time_max and Google Calendar
rejected the list call — RFC 3339 requires an offset — while the
gateway flattened Google's diagnostic body into a bare "HTTP 400",
so the plan died opaquely before its delete step. Proven live: the
naive call reproduced the 400 and the "+01:00"-qualified call
succeeded.

The gateway now qualifies naive bounds with the local timezone
(Africa/Casablanca — the same convention add_event uses), expands
date-only bounds to the full local day, rejects unparseable or
inverted ranges without calling Google (fail-closed), and surfaces
Google's own error message alongside the status code. The bare
"HTTP <code>" error string is unchanged, because delete_event
matches it exactly for its idempotency check.
"""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
import urllib.parse
from unittest import mock

from features.calendar.infrastructure.adapters.google_calendar_gateway import (
    GoogleCalendarGateway,
)


def _gateway(responder):
    gateway = object.__new__(GoogleCalendarGateway)
    calls = []

    def fake_request(method, path, body=None):
        calls.append((method, path))
        return responder(method, path)

    gateway._request = fake_request
    return gateway, calls


def _ok_empty(method, path):
    return {"ok": True, "data": {"items": []}}


def _query_of(path: str) -> dict:
    return urllib.parse.parse_qs(urllib.parse.urlparse(path).query)


class TestListEventsRangeQualification(unittest.TestCase):
    def test_naive_bounds_qualified_with_local_offset(self):
        # January 2026: Africa/Casablanca is UTC+1 under every tzdata
        # version in play (pre- and post-2026c), so the literal offset
        # is stable on the VM, the phone, and the VPS.
        gateway, calls = _gateway(_ok_empty)
        result = gateway.list_events("2026-01-15T23:58:00", "2026-01-16T00:01:00", 10)
        self.assertTrue(result["ok"])
        query = _query_of(calls[0][1])
        self.assertEqual(query["timeMin"], ["2026-01-15T23:58:00+01:00"])
        self.assertEqual(query["timeMax"], ["2026-01-16T00:01:00+01:00"])

    def test_qualified_bounds_keep_their_offset(self):
        gateway, calls = _gateway(_ok_empty)
        result = gateway.list_events("2026-10-29T10:00:00Z", "2026-10-29T12:00:00+02:00", 10)
        self.assertTrue(result["ok"])
        query = _query_of(calls[0][1])
        self.assertEqual(query["timeMin"], ["2026-10-29T10:00:00+00:00"])
        self.assertEqual(query["timeMax"], ["2026-10-29T12:00:00+02:00"])

    def test_date_only_bounds_expand_to_full_local_day(self):
        gateway, calls = _gateway(_ok_empty)
        result = gateway.list_events("2026-01-15", "2026-01-15", 10)
        self.assertTrue(result["ok"])
        query = _query_of(calls[0][1])
        self.assertEqual(query["timeMin"], ["2026-01-15T00:00:00+01:00"])
        self.assertEqual(query["timeMax"], ["2026-01-15T23:59:59+01:00"])

    def test_inverted_range_rejected_without_calling_google(self):
        gateway, calls = _gateway(_ok_empty)
        result = gateway.list_events("2026-10-30T00:00:00", "2026-10-29T00:00:00", 10)
        self.assertFalse(result["ok"])
        self.assertEqual(calls, [])

    def test_unparseable_bound_rejected_without_calling_google(self):
        gateway, calls = _gateway(_ok_empty)
        self.assertFalse(gateway.list_events("not-a-date", "2026-10-29", 10)["ok"])
        self.assertFalse(gateway.list_events("", "2026-10-29", 10)["ok"])
        self.assertEqual(calls, [])


class TestListEventsErrorSurfacing(unittest.TestCase):
    def test_google_detail_appended_to_error(self):
        def responder(method, path):
            return {"ok": False, "error": "HTTP 400", "detail": "Invalid timeMin"}

        gateway, _ = _gateway(responder)
        result = gateway.list_events("2026-10-29T00:00:00", "2026-10-30T00:00:00", 10)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "HTTP 400: Invalid timeMin")

    def test_bare_error_preserved_without_detail(self):
        def responder(method, path):
            return {"ok": False, "error": "HTTP 500"}

        gateway, _ = _gateway(responder)
        result = gateway.list_events("2026-10-29T00:00:00", "2026-10-30T00:00:00", 10)
        self.assertEqual(result["error"], "HTTP 500")

    def test_events_mapping_still_works(self):
        def responder(method, path):
            return {
                "ok": True,
                "data": {
                    "items": [
                        {
                            "id": "evt1",
                            "summary": "لقاء",
                            "start": {"dateTime": "2026-10-29T10:00:00+01:00"},
                            "end": {"dateTime": "2026-10-29T11:00:00+01:00"},
                            "description": "",
                        }
                    ]
                },
            }

        gateway, _ = _gateway(responder)
        result = gateway.list_events("2026-10-29", "2026-10-29", 10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["events"][0]["event_id"], "evt1")
        self.assertEqual(result["events"][0]["title"], "لقاء")


class TestRequestErrorDetail(unittest.TestCase):
    def _gateway_with_token(self):
        gateway = object.__new__(GoogleCalendarGateway)
        gateway._refresh_access_token = lambda: True
        gateway._access_token = "token"
        return gateway

    def test_request_extracts_google_error_message(self):
        gateway = self._gateway_with_token()
        body = json.dumps({"error": {"message": "Invalid timeMin"}}).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://example", 400, "Bad Request", {}, io.BytesIO(body)
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            result = gateway._request("GET", "/calendars/primary/events")
        self.assertEqual(result["error"], "HTTP 400")
        self.assertEqual(result["detail"], "Invalid timeMin")

    def test_request_without_json_body_has_no_detail(self):
        gateway = self._gateway_with_token()
        error = urllib.error.HTTPError(
            "https://example", 500, "Server Error", {}, io.BytesIO(b"not json")
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            result = gateway._request("GET", "/calendars/primary/events")
        self.assertEqual(result["error"], "HTTP 500")
        self.assertNotIn("detail", result)


if __name__ == "__main__":
    unittest.main()
