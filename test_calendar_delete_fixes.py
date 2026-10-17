"""Behavioral tests for the calendar_delete fixes (2026-10-17).

1. Idempotent delete: HTTP 404/410 from the API -> success with note.
2. Other HTTP errors (e.g. 500) still surface as failures.
3. The audit helper extracts the error string for failed tool runs.
"""

import unittest
from unittest.mock import patch

from core.agent._tool_pipeline import _failure_error_for_audit
from features.calendar.application.dto.calendar import DeleteEventRequest
from features.calendar.application.use_cases.delete_event import (
    DeleteEventUseCase,
)
from features.calendar.infrastructure.adapters.google_calendar_gateway import (
    GoogleCalendarGateway,
)


class TestIdempotentDeleteGateway(unittest.TestCase):
    def _delete_with(self, request_result):
        gw = GoogleCalendarGateway.__new__(GoogleCalendarGateway)
        with patch.object(
            GoogleCalendarGateway, "_request", return_value=request_result
        ):
            return gw.delete_event("evt-123")

    def test_404_becomes_idempotent_success(self):
        res = self._delete_with({"ok": False, "error": "HTTP 404"})
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("already_deleted"))

    def test_410_becomes_idempotent_success(self):
        res = self._delete_with({"ok": False, "error": "HTTP 410"})
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("already_deleted"))

    def test_500_stays_failure(self):
        res = self._delete_with({"ok": False, "error": "HTTP 500"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "HTTP 500")

    def test_real_delete_unchanged(self):
        res = self._delete_with({"ok": True, "data": {}})
        self.assertEqual(res, {"ok": True})


class FakeAlreadyDeletedGateway:
    def delete_event(self, event_id):
        return {"ok": True, "already_deleted": True}


class FakeOkGateway:
    def delete_event(self, event_id):
        return {"ok": True}


class FakeFailGateway:
    def delete_event(self, event_id):
        return {"ok": False, "error": "HTTP 500"}


class TestDeleteUseCaseMessages(unittest.TestCase):
    def test_already_deleted_message(self):
        uc = DeleteEventUseCase(FakeAlreadyDeletedGateway())
        res = uc.execute(DeleteEventRequest(event_id="evt-123"))
        self.assertTrue(res.ok)
        self.assertEqual(res.message, "الموعد محذوف مسبقًا.")

    def test_normal_delete_message(self):
        uc = DeleteEventUseCase(FakeOkGateway())
        res = uc.execute(DeleteEventRequest(event_id="evt-123"))
        self.assertTrue(res.ok)
        self.assertEqual(res.message, "تم حذف الموعد.")

    def test_failure_message_preserved(self):
        uc = DeleteEventUseCase(FakeFailGateway())
        res = uc.execute(DeleteEventRequest(event_id="evt-123"))
        self.assertFalse(res.ok)
        self.assertIn("HTTP 500", res.message)


class TestAuditErrorExtraction(unittest.TestCase):
    def test_extracts_error_field(self):
        self.assertEqual(
            _failure_error_for_audit({"ok": False, "error": "HTTP 404"}),
            "HTTP 404",
        )

    def test_falls_back_to_message(self):
        self.assertEqual(
            _failure_error_for_audit(
                {"ok": False, "message": "تعذر حذف الموعد: HTTP 404"}
            ),
            "تعذر حذف الموعد: HTTP 404",
        )

    def test_none_when_nothing_to_record(self):
        self.assertIsNone(_failure_error_for_audit({"ok": True}))
        self.assertIsNone(_failure_error_for_audit(None))
        self.assertIsNone(_failure_error_for_audit("not-a-dict"))

    def test_truncates_long_errors(self):
        res = _failure_error_for_audit(
            {"ok": False, "error": "x" * 1000}
        )
        self.assertEqual(len(res), 300)


if __name__ == "__main__":
    unittest.main()
