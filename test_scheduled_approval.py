"""Behavioral tests for escalation path (ب).

Scheduled destructive tools suspend for a 180s Telegram approval window
instead of being hard-rejected. Approval → execute. Denial or silence →
final cancel (history-logged + user notified). Never executes without
explicit approval.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test-env shims: core.llm imports python-dotenv and openai, which are installed
# in the VPS .venv but not in this minimal environment. Stub them so the import
# chain loads — nothing under test touches their behavior.
import types as _types

_dotenv_stub = _types.ModuleType("dotenv")
_dotenv_stub.dotenv_values = lambda *a, **k: {}
sys.modules.setdefault("dotenv", _dotenv_stub)

_openai_stub = _types.ModuleType("openai")


class _OpenAIStub:
    def __init__(self, *a, **k):
        raise RuntimeError("openai stub: not usable in tests")


_openai_stub.OpenAI = _OpenAIStub
sys.modules.setdefault("openai", _openai_stub)

from core import scheduled_approval as sa
from core.agent._tool_pipeline import _ToolPipelineMixin
from core.policy import Policy


def _isolated_home(testcase):
    """Point Path.home() at a temp dir for the duration of the test."""
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    patcher = mock.patch.dict(os.environ, {"HOME": tmp.name})
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return Path(tmp.name)


def _queue_base(home: Path) -> Path:
    return home / "ALIX-Agent" / "pending_approvals"


class QueueTest(unittest.TestCase):
    def test_request_verdict_roundtrip(self):
        home = _isolated_home(self)
        req = sa.request_approval(
            "t1", "nightly", "calendar_delete", {"event_id": "x"}, "destructive"
        )
        self.assertEqual(req["status"], "pending")
        self.assertEqual(req["tool_name"], "calendar_delete")
        sa.write_verdict(req["id"], True, "ok")
        verdict = sa.await_verdict(req["id"], timeout_s=5)
        self.assertIsNotNone(verdict)
        self.assertTrue(verdict["approved"])

    def test_await_timeout_returns_none(self):
        _isolated_home(self)
        req = sa.request_approval(
            "t1", "n", "calendar_delete", {}, "destructive"
        )
        self.assertIsNone(sa.await_verdict(req["id"], timeout_s=0))

    def test_expire_archives_request(self):
        home = _isolated_home(self)
        req = sa.request_approval(
            "t1", "n", "calendar_delete", {}, "destructive"
        )
        sa.expire_request(req["id"], "timeout")
        base = _queue_base(home)
        self.assertFalse((base / "requests" / f"{req['id']}.json").exists())
        archived = json.loads(
            (base / "archive" / f"{req['id']}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(archived["status"], "expired")
        self.assertEqual(archived["reason"], "timeout")

    def test_complete_archives_request(self):
        home = _isolated_home(self)
        req = sa.request_approval(
            "t1", "n", "calendar_delete", {}, "destructive"
        )
        sa.write_verdict(req["id"], True)
        sa.complete_request(req["id"], "approved", "وافق المستخدم")
        base = _queue_base(home)
        self.assertFalse((base / "requests" / f"{req['id']}.json").exists())
        self.assertFalse((base / "results" / f"{req['id']}.json").exists())
        archived = json.loads(
            (base / "archive" / f"{req['id']}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(archived["status"], "approved")

    def test_late_verdict_is_ignored(self):
        home = _isolated_home(self)
        req = sa.request_approval(
            "t1", "n", "calendar_delete", {}, "destructive"
        )
        sa.expire_request(req["id"], "timeout")
        sa.write_verdict(req["id"], True)  # arrives after expiry
        base = _queue_base(home)
        self.assertFalse((base / "results" / f"{req['id']}.json").exists())

    def test_notify_take_roundtrip(self):
        _isolated_home(self)
        sa.notify_user("المهمة أُلغيت")
        msgs = sa.take_notifications()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["text"], "المهمة أُلغيت")
        # Taking archives: second take is empty.
        self.assertEqual(sa.take_notifications(), [])

    def test_list_pending_skips_expired(self):
        home = _isolated_home(self)
        req = sa.request_approval(
            "t1", "n", "calendar_delete", {}, "destructive"
        )
        self.assertEqual(len(sa.list_pending()), 1)
        sa.expire_request(req["id"], "timeout")
        self.assertEqual(sa.list_pending(), [])


class StubAgent(_ToolPipelineMixin):
    def __init__(self):
        self.policy = Policy()
        self.policy.scheduled_mode = True
        self.policy.scheduled_allow = "execute"
        self.audits = []
        self.logged = []

    def audit(self, *args, **kwargs):
        self.audits.append((args, kwargs))

    def _log_history_action(self, name, arguments, result):
        self.logged.append({"tool": name, "result": result})


class ConfirmBranchTest(unittest.TestCase):
    def test_approval_granted_executes(self):
        home = _isolated_home(self)
        agent = StubAgent()
        rid_holder = {}
        real_request = sa.request_approval

        def spy_request(**kwargs):
            req = real_request(**kwargs)
            rid_holder["id"] = req["id"]
            return req

        def approve_soon():
            time.sleep(0.3)
            sa.write_verdict(rid_holder["id"], True)

        with mock.patch.object(
            sa, "request_approval", side_effect=spy_request
        ), mock.patch.object(sa, "POLL_INTERVAL_S", 0.05):
            t = threading.Thread(target=approve_soon)
            t.start()
            try:
                self.assertTrue(
                    agent.confirm_tool("calendar_delete", {"event_id": "x"})
                )
            finally:
                t.join()
        # Approved → the request is archived so the bot never re-cards it.
        base = _queue_base(home)
        self.assertFalse(
            (base / "requests" / f"{rid_holder['id']}.json").exists()
        )
        archived = json.loads(
            (
                base / "archive" / f"{rid_holder['id']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(archived["status"], "approved")

    def test_denial_cancels_finally(self):
        home = _isolated_home(self)
        agent = StubAgent()
        with mock.patch.object(
            sa, "await_verdict", return_value={"approved": False, "detail": "no"}
        ):
            self.assertFalse(
                agent.confirm_tool("calendar_delete", {"event_id": "x"})
            )
        # Cancelled → history-logged with the contract wording.
        self.assertEqual(len(agent.logged), 1)
        entry = agent.logged[0]
        self.assertEqual(entry["tool"], "calendar_delete")
        self.assertFalse(entry["result"]["ok"])
        self.assertTrue(entry["result"]["cancelled"])
        self.assertIn("أُلغيت", entry["result"]["message"])
        # …and the user is notified.
        msgs = sa.take_notifications()
        self.assertEqual(len(msgs), 1)
        self.assertIn("أُلغيت", msgs[0]["text"])
        # …and the request is archived, not left pending.
        self.assertEqual(sa.list_pending(), [])

    def test_silence_cancels_finally(self):
        _isolated_home(self)
        agent = StubAgent()
        with mock.patch.object(sa, "await_verdict", return_value=None):
            self.assertFalse(
                agent.confirm_tool("calendar_delete", {"event_id": "x"})
            )
        kinds = [a[0][0] for a in agent.audits]
        self.assertIn("scheduled_approval_requested", kinds)
        self.assertIn("scheduled_approval_cancelled", kinds)
        self.assertEqual(len(agent.logged), 1)
        self.assertIn("180 ثانية", agent.logged[0]["result"]["message"])

    def test_denylist_still_hard_denied(self):
        home = _isolated_home(self)
        agent = StubAgent()
        # browse_page is on SCHEDULER_DENIED_TOOLS: no escalation, no request.
        self.assertFalse(agent.confirm_tool("browse_page", {"url": "x"}))
        base = _queue_base(home)
        req_dir = base / "requests"
        self.assertEqual(
            list(req_dir.glob("*.json")) if req_dir.exists() else [], []
        )

    def test_non_destructive_over_ceiling_denied_without_escalation(self):
        home = _isolated_home(self)
        agent = StubAgent()
        agent.policy.scheduled_allow = "read"
        # calendar_add is "execute": over a "read" ceiling, not destructive.
        self.assertFalse(agent.confirm_tool("calendar_add", {"title": "t"}))
        base = _queue_base(home)
        req_dir = base / "requests"
        self.assertEqual(
            list(req_dir.glob("*.json")) if req_dir.exists() else [], []
        )

    def test_queue_failure_is_fail_closed(self):
        _isolated_home(self)
        agent = StubAgent()
        with mock.patch.object(
            sa, "request_approval", side_effect=OSError("disk full")
        ):
            self.assertFalse(
                agent.confirm_tool("calendar_delete", {"event_id": "x"})
            )


class PromptContractTest(unittest.TestCase):
    def test_single_approval_rule_present(self):
        from core.agent.prompts import SYSTEM_PROMPT

        self.assertIn("البوابة الوحيدة", SYSTEM_PROMPT)

    def test_outcome_wording_present(self):
        from core.agent.prompts import SYSTEM_PROMPT

        self.assertIn("المهمة نُفِّذت", SYSTEM_PROMPT)
        self.assertIn("المهمة أُلغيت", SYSTEM_PROMPT)

    def test_schedule_task_description_mentions_escalation(self):
        # Regression guard: the schedule_task description must document
        # escalation path (ب), never claim destructive is always forbidden
        # (that blanket ban made the LLM refuse to schedule, leaving the
        # scheduled approval queue unreachable).
        from core.agent.prompts import TOOLS

        desc = next(
            t["function"]["description"]
            for t in TOOLS
            if t["function"]["name"] == "schedule_task"
        )
        self.assertIn("180", desc)
        self.assertNotIn("ممنوع دائمًا", desc)

    def test_undo_message_uses_cancelled_wording(self):
        # Wording-contract regression guard: the undo success message must
        # say "أُلغيت", never the old "تم التراجع:" phrasing.
        src = (
            Path(__file__).parent / "core" / "agent" / "_tool_pipeline.py"
        ).read_text(encoding="utf-8")
        self.assertIn("المهمة أُلغيت", src)
        self.assertNotIn("تم التراجع:", src)


class DenialRetryBlockedTest(unittest.TestCase):
    """Structural single-denial: a tool denied once in a turn is never
    re-carded in the same turn (fixes the duplicate-card-after-timeout
    bug seen live: the LLM re-called a timed-out tool and the user got
    a second approval card)."""

    def _interactive_denying_agent(self):
        agent = StubAgent()
        agent.policy.scheduled_mode = False
        calls = []

        def deny(name, arguments, level):
            calls.append(name)
            return False

        agent.confirm_fn = deny
        agent.confirm_calls = calls
        return agent

    def test_retry_after_denial_blocked_without_recard(self):
        agent = self._interactive_denying_agent()
        self.assertFalse(
            agent.confirm_tool("calendar_delete", {"event_id": "x"})
        )
        # Same tool, same turn → blocked; the confirmer is NOT invoked again.
        self.assertFalse(
            agent.confirm_tool("calendar_delete", {"event_id": "y"})
        )
        self.assertEqual(agent.confirm_calls, ["calendar_delete"])
        self.assertIn("calendar_delete", agent._denied_this_turn)
        kinds = [a[0][0] for a in agent.audits]
        self.assertIn("tool_confirmation_retry_blocked", kinds)

    def test_different_tool_still_allowed_after_denial(self):
        agent = self._interactive_denying_agent()
        self.assertFalse(
            agent.confirm_tool("calendar_delete", {"event_id": "x"})
        )
        self.assertFalse(
            agent.confirm_tool("calendar_add", {"title": "t"})
        )
        self.assertEqual(
            agent.confirm_calls, ["calendar_delete", "calendar_add"]
        )

    def test_new_turn_clears_denial_registry(self):
        agent = self._interactive_denying_agent()
        self.assertFalse(
            agent.confirm_tool("calendar_delete", {"event_id": "x"})
        )
        # run() resets the registry on every new user message.
        agent._denied_this_turn = set()
        self.assertFalse(
            agent.confirm_tool("calendar_delete", {"event_id": "x"})
        )
        self.assertEqual(
            agent.confirm_calls, ["calendar_delete", "calendar_delete"]
        )

    def test_denial_error_carries_no_retry_instruction(self):
        agent = self._interactive_denying_agent()
        result = agent.execute_tool(
            "calendar_delete", {"event_id": "x"}
        )
        self.assertFalse(result["ok"])
        self.assertIn("رفض المستخدم", result["error"])
        self.assertIn("لا تستدع", result["error"])


if __name__ == "__main__":
    unittest.main()
