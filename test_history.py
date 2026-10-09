"""Behavioral tests for the history/undo feature slice."""

import tempfile
import unittest
from pathlib import Path

from features.history.application.dto.history import (
    LogActionRequest,
    ListHistoryRequest,
)
from features.history.application.use_cases.history_use_cases import (
    ListHistoryUseCase,
    LogActionUseCase,
    UndoLastUseCase,
)
from features.history.composition import build_history_controllers
from features.history.domain.action import ActionRecord
from features.history.infrastructure.adapters.jsonl_action_store import (
    JsonlActionStore,
)
from features.history.inverse import compute_inverse, summarize_action


class TestActionDomain(unittest.TestCase):
    def test_reversible(self):
        a = ActionRecord(
            tool_name="calendar_add",
            arguments={},
            timestamp="2026-10-09T00:00:00",
            ok=True,
            inverse={"tool": "calendar_delete", "arguments": {}},
        )
        self.assertTrue(a.is_reversible())

    def test_not_reversible_when_undone(self):
        a = ActionRecord(
            tool_name="calendar_add",
            arguments={},
            timestamp="2026-10-09T00:00:00",
            ok=True,
            inverse={"tool": "x", "arguments": {}},
            undone=True,
        )
        self.assertFalse(a.is_reversible())

    def test_not_reversible_on_failure(self):
        a = ActionRecord(
            tool_name="calendar_add",
            arguments={},
            timestamp="2026-10-09T00:00:00",
            ok=False,
            inverse={"tool": "x", "arguments": {}},
        )
        self.assertFalse(a.is_reversible())


class TestInverse(unittest.TestCase):
    def test_calendar_add_inverse(self):
        inv = compute_inverse(
            "calendar_add",
            {"title": "x"},
            {"ok": True, "event_id": "evt-123"},
        )
        self.assertEqual(inv["tool"], "calendar_delete")
        self.assertEqual(inv["arguments"]["event_id"], "evt-123")

    def test_no_inverse_on_failure(self):
        self.assertIsNone(
            compute_inverse("calendar_add", {}, {"ok": False})
        )

    def test_no_inverse_for_irreversible(self):
        self.assertIsNone(
            compute_inverse(
                "phone_call", {}, {"ok": True}
            )
        )

    def test_summarize(self):
        s = summarize_action(
            "calendar_add", {"title": "اجتماع"}, {"ok": True}
        )
        self.assertIn("اجتماع", s)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = JsonlActionStore(path=self.tmp / "actions.jsonl")

    def test_append_and_list(self):
        self.store.append(
            {
                "tool_name": "calendar_add",
                "arguments": {"title": "x"},
                "ok": True,
                "summary": "test",
                "inverse": {"tool": "y", "arguments": {}},
            }
        )
        records = self.store.list_recent(10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["tool_name"], "calendar_add")

    def test_mark_undone(self):
        self.store.append(
            {"tool_name": "a", "arguments": {}, "ok": True}
        )
        self.store.append(
            {"tool_name": "b", "arguments": {}, "ok": True}
        )
        self.assertTrue(self.store.mark_undone(0))
        records = self.store.list_recent(10)
        # Most recent first; index 0 = "b"
        self.assertTrue(records[0]["undone"])
        self.assertFalse(records[1]["undone"])

    def test_empty_store(self):
        self.assertEqual(self.store.list_recent(10), [])


class TestUseCases(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = JsonlActionStore(path=self.tmp / "actions.jsonl")

    def test_log_and_list(self):
        log = LogActionUseCase(store=self.store)
        log.execute(
            LogActionRequest(
                tool_name="calendar_add",
                arguments={"title": "x"},
                ok=True,
                summary="added",
                inverse={"tool": "calendar_delete", "arguments": {}},
            )
        )
        lst = ListHistoryUseCase(store=self.store)
        result = lst.execute(ListHistoryRequest(limit=10))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.actions), 1)

    def test_undo_finds_reversible(self):
        log = LogActionUseCase(store=self.store)
        log.execute(
            LogActionRequest(
                tool_name="phone_call",  # not reversible
                arguments={},
                ok=True,
            )
        )
        log.execute(
            LogActionRequest(
                tool_name="calendar_add",
                arguments={},
                ok=True,
                inverse={"tool": "calendar_delete", "arguments": {}},
            )
        )
        undo = UndoLastUseCase(store=self.store)
        result = undo.execute()
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.undone_action)
        self.assertEqual(
            result.undone_action["inverse"]["tool"],
            "calendar_delete",
        )

    def test_undo_none_reversible(self):
        undo = UndoLastUseCase(store=self.store)
        result = undo.execute()
        self.assertFalse(result.ok)


class TestComposition(unittest.TestCase):
    def test_build(self):
        c = build_history_controllers(policy=None)
        self.assertIn("history", c)
        self.assertIn("undo", c)
        self.assertIn("log_action", c)


if __name__ == "__main__":
    unittest.main()
