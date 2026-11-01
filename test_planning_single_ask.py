"""Single-ask principle (owner's ruling, 2026-11-01).

"Give it a request; it asks me ONCE for approval; on my
approval it answers at once — without re-asking the same
question and without repeated demands."

The audit found most surfaces already compliant (one card
per turn with a structural no-retry guard, terminal denial
wording, one-shot escalations, one cancellation notice).
Two structural re-ask loops violated the principle and are
pinned here:

1. Self-diagnosis proposals: an EXPIRED proposal (card not
   answered in 180s) was deliberately re-proposed every
   weekly cycle for as long as the signal persisted. Now an
   expired fingerprint is suppressed and re-proposed only
   on NEW evidence (the signal's failure/count value grew
   past the recorded one).
2. Decision-6 scheduled clarifications: a recurring task
   re-asked its question at every occurrence. Now an ask
   ledger delivers a scheduled clarification at most once
   per ASK_REPEAT_COOLDOWN_DAYS per goal.

And one wording gap: the pipeline's denial result forbade
re-CALLING the tool but not verbally re-OFFERING the retry
(the model offered one anyway in the 2026-11-01 deletion
transcript) — the result text now forbids both, keeping the
pinned denial prefix the plan executor classifies by.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.planning.ask import clarification_key
from features.planning.application.dto.planning import (
    CreatePlanRequest,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.use_cases.create_plan import (
    CreatePlanUseCase,
)
from features.planning.infrastructure.adapters.json_ask_ledger import (
    JsonAskLedger,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)
from features.planning.infrastructure.adapters.readback_verifier import (
    ReadBackVerifier,
)

NOW = datetime(2026, 11, 1, 20, 30, tzinfo=timezone.utc)
GOAL = "احفظ تقرير الذهب في ملف"

ALLOWLIST = frozenset({"web_search", "write_file"})
SCHEMAS = {
    "web_search": frozenset({"query"}),
    "write_file": frozenset({"path", "content"}),
}
LEVELS = {"web_search": "read", "write_file": "write"}
VERIFIABLE = ReadBackVerifier.default_spec_tools()


def fixed_clock():
    return NOW


class FakePlanner(PlannerPort):
    def __init__(self, plan_draft=None):
        self._plan_draft = plan_draft or {"steps": []}

    def plan(self, goal, prior_actions, context):
        return self._plan_draft

    def decompose(self, goal, failed_step, remaining_steps):
        return {"mode": "give_up"}


class SpyNotifier:
    def __init__(self):
        self.clarifications = []

    def created(self, plan, approval_steps):
        pass

    def decomposed(self, plan, failed_step, new_step_ids):
        pass

    def escalated(self, plan, failed_step, reason):
        pass

    def finished(self, plan):
        pass

    def recovered(self, plans):
        pass

    def clarification(self, goal, question):
        self.clarifications.append((goal, question))

    def plan_notices(self, plan, notices):
        pass


class StubLedger:
    """In-memory AskLedgerPort with a preset last-asked time."""

    def __init__(self, last=None):
        self._last = last
        self.records = []

    def last_asked(self, key):
        return self._last

    def record(self, key, when):
        self.records.append((key, when))
        self._last = when


WRITE_DRAFT = {
    "steps": [
        {"intent": "بحث", "tool": "web_search",
         "args": {"query": "ذهب"}},
        {"intent": "حفظ", "tool": "write_file",
         "args": {"path": "gold.txt", "content": "x"}},
    ]
}


class AskGateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.notifier = SpyNotifier()

    def create(self, planner, origin="scheduled", ledger="unset"):
        kw = {}
        if ledger != "unset":
            kw["ask_ledger"] = ledger
        use_case = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
            notifier=self.notifier,
            tool_levels=dict(LEVELS),
            verifiable_tools=VERIFIABLE,
            **kw,
        )
        return use_case.execute(
            CreatePlanRequest(goal=GOAL, origin=origin)
        )


class TestScheduledAskGate(AskGateCase):
    def test_first_ask_delivers_and_records(self):
        ledger = StubLedger()
        outcome = self.create(
            FakePlanner(WRITE_DRAFT), ledger=ledger
        )
        self.assertEqual(outcome.reason, "clarification_needed")
        self.assertFalse(outcome.ask_repeated)
        self.assertEqual(len(self.notifier.clarifications), 1)
        self.assertEqual(len(ledger.records), 1)
        self.assertEqual(
            ledger.records[0][0], clarification_key(GOAL)
        )

    def test_repeat_inside_cooldown_is_silent(self):
        ledger = StubLedger(last=NOW - timedelta(days=2))
        outcome = self.create(
            FakePlanner(WRITE_DRAFT), ledger=ledger
        )
        self.assertEqual(outcome.reason, "clarification_needed")
        self.assertTrue(outcome.ask_repeated)
        self.assertEqual(self.notifier.clarifications, [])
        self.assertEqual(ledger.records, [])  # not re-stamped

    def test_after_cooldown_asks_once_more(self):
        ledger = StubLedger(last=NOW - timedelta(days=8))
        outcome = self.create(
            FakePlanner(WRITE_DRAFT), ledger=ledger
        )
        self.assertFalse(outcome.ask_repeated)
        self.assertEqual(len(self.notifier.clarifications), 1)
        self.assertEqual(len(ledger.records), 1)

    def test_planner_clarify_is_gated_too_when_scheduled(self):
        ledger = StubLedger(last=NOW - timedelta(hours=3))
        outcome = self.create(
            FakePlanner({"clarify": "أي مجلد؟"}), ledger=ledger
        )
        self.assertTrue(outcome.ask_repeated)
        self.assertEqual(self.notifier.clarifications, [])

    def test_interactive_clarify_never_gated(self):
        ledger = StubLedger(last=NOW - timedelta(minutes=5))
        outcome = self.create(
            FakePlanner({"clarify": "أي مجلد؟"}),
            origin="interactive",
            ledger=ledger,
        )
        self.assertFalse(outcome.ask_repeated)
        self.assertEqual(len(self.notifier.clarifications), 1)

    def test_no_ledger_keeps_legacy_delivery(self):
        outcome = self.create(FakePlanner(WRITE_DRAFT))
        self.assertFalse(outcome.ask_repeated)
        self.assertEqual(len(self.notifier.clarifications), 1)


class TestAskLedgerFile(unittest.TestCase):
    def test_roundtrip_and_key_stability(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = JsonAskLedger(Path(tmp) / "asked.json")
            key = clarification_key("  احفظ   التقرير ")
            self.assertIsNone(ledger.last_asked(key))
            ledger.record(key, NOW)
            self.assertEqual(ledger.last_asked(key), NOW)
            # Normalization: spacing/case variants are one ask.
            self.assertEqual(
                clarification_key("احفظ التقرير"),
                clarification_key("  احفظ   التقرير "),
            )

    def test_corrupt_state_reads_as_never_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asked.json"
            path.write_text("{broken", encoding="utf-8")
            ledger = JsonAskLedger(path)
            self.assertIsNone(ledger.last_asked("k"))
            ledger.record("k", NOW)  # and recording still works
            self.assertEqual(ledger.last_asked("k"), NOW)


class TestDenialWording(unittest.TestCase):
    def test_pipeline_text_forbids_reoffer_keeps_prefix(self):
        source = (
            Path(__file__).parent
            / "core" / "agent" / "_tool_pipeline.py"
        ).read_text(encoding="utf-8")
        self.assertIn("رفض المستخدم تنفيذ العملية", source)
        self.assertIn("ولا تعرض إعادة المحاولة", source)
        # The plan executor's denial classification pins this
        # exact prefix — it must stay the string's start.
        from features.planning.application.use_cases.run_plan import (
            APPROVAL_DENIED_ERROR_PREFIX,
        )

        self.assertTrue(
            "رفض المستخدم تنفيذ العملية".startswith(
                APPROVAL_DENIED_ERROR_PREFIX
            )
        )


# -- draft_proposals: expired means suppressed ---------------


def _load_draft_proposals():
    path = (
        Path(__file__).parent / "scripts" / "draft_proposals.py"
    )
    spec = importlib.util.spec_from_file_location(
        "draft_proposals_under_test", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeApproval:
    def __init__(self):
        self.requests = []

    def request_approval(self, **kw):
        rid = f"req-{len(self.requests) + 1}"
        self.requests.append(kw)
        return {"id": rid}

    def await_verdict(self, rid, timeout_s=None):
        return None  # silence: every card expires

    def complete_request(self, rid, status, reason):
        pass


class TestProposalSingleAsk(unittest.TestCase):
    def setUp(self):
        self.dp = _load_draft_proposals()
        self.sa = FakeApproval()
        self.dp.sa = self.sa
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.proposals = root / "proposals"
        self.outbox = root / "outbox"
        self.diag = root / "diagnosis.json"

    def _run(self, failures):
        signal = {
            "type": "tool_failures",
            "tool": "web_fetch",
            "failures": failures,
            "calls": 20,
            "summaries": ["boom"],
        }
        self.diag.write_text(
            json.dumps(
                {"signals": [signal], "window_days": 7}
            ),
            encoding="utf-8",
        )
        argv = sys.argv
        sys.argv = [
            "draft_proposals.py",
            "--diagnosis", str(self.diag),
            "--proposals-dir", str(self.proposals),
            "--outbox", str(self.outbox),
        ]
        try:
            return self.dp.main()
        finally:
            sys.argv = argv

    def _index(self):
        return json.loads(
            (self.proposals / "index.json").read_text(
                encoding="utf-8"
            )
        )

    def test_expire_then_suppressed_then_new_evidence(self):
        # Cycle 1: proposed, unanswered -> expires.
        self.assertEqual(self._run(failures=5), 0)
        self.assertEqual(len(self.sa.requests), 1)
        index = self._index()
        self.assertEqual(len(index), 1)
        entry = next(iter(index.values()))
        # The expired entry SURVIVES (it is the suppression
        # record) with the evidence it was asked at.
        self.assertEqual(entry["status"], "expired")
        self.assertEqual(entry["signal_evidence"], 5)

        # Cycle 2: same signal, same size -> NOT re-asked.
        self.assertEqual(self._run(failures=5), 0)
        self.assertEqual(len(self.sa.requests), 1)

        # Cycle 3: the signal GREW (new evidence) -> asked
        # once more, and the record moves to the new value.
        self.assertEqual(self._run(failures=9), 0)
        self.assertEqual(len(self.sa.requests), 2)
        entry = next(iter(self._index().values()))
        self.assertEqual(entry["signal_evidence"], 9)


if __name__ == "__main__":
    unittest.main()
