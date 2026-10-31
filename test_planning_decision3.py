"""Decision 3 — boot-time recovery, report-only read-back,
compensate retired (owner's rulings, 2026-11-01).

Rulings pinned here:
- §2 REPORT-ONLY: an interrupted step stays BLOCKED with
  outcome_unknown; the recovery read-back outcome is recorded
  on the step (verify_outcome + an evidence line in error) and
  surfaced in the single recovery digest. It never resolves
  the step and never resumes the plan.
- §3 RETIREMENT: PlanStep / PlanStepRecord have no compensate
  field; a legacy stored record carrying the key loads fine
  and drops the key on re-save.
- TIMING: recovery is serialized across processes sharing the
  store (flock) so normalization — and the digest — happen
  exactly once; the agent exposes recover_planning_at_boot()
  delegating to the same once-per-instance fail-soft path.
"""
import dataclasses
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.entities import PlanStep
from domain.planning.states import BlockedReason, StepState

from features.planning.application.dto.planning import (
    PlanRecord,
    PlanStepRecord,
)
from features.planning.application.ports.verifier import (
    VerificationOutcome,
    Verdict,
    VerifierPort,
)
from features.planning.application.use_cases.recover_plans import (
    RecoverPlansUseCase,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)
from features.planning.interfaces import formatting

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-11-01T12:00:00+00:00"


def fixed_clock():
    return NOW


def step_record(step_id="s1", state="running", tool="calendar_add"):
    return PlanStepRecord(
        step_id=step_id,
        intent="خطوة",
        tool=tool,
        args={"title": "اجتماع", "start": "2026-11-02T10:00:00"},
        state=state,
        idempotency_key=f"p_d3:{step_id}",
        created_at=NOW_ISO,
        updated_at=NOW_ISO,
    )


def plan_record(steps, awaiting="s1"):
    return PlanRecord(
        plan_id="p_d3",
        goal="هدف تجريبي",
        origin="interactive",
        steps=tuple(steps),
        prior_actions=(),
        replans_used=0,
        replans_max=2,
        awaiting_step_id=awaiting,
        escalated=False,
        created_at=NOW_ISO,
        updated_at=NOW_ISO,
        expires_at="2026-11-02T12:00:00+00:00",
        state="running",
    )


class FakeVerifier(VerifierPort):
    def __init__(self, outcome=None, raises=False):
        self._outcome = outcome
        self._raises = raises
        self.calls = []

    def verify(self, step, result):
        self.calls.append((step.step_id, dict(result)))
        if self._raises:
            raise RuntimeError("verifier blew up")
        return self._outcome


class RecordingNotifier:
    def __init__(self):
        self.recovered_calls = []

    def created(self, plan, approval_steps):
        pass

    def decomposed(self, plan, failed_step, new_step_ids):
        pass

    def escalated(self, plan, failed_step, reason):
        pass

    def finished(self, plan):
        pass

    def recovered(self, plans):
        self.recovered_calls.append(list(plans))


class Decision3Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.notifier = RecordingNotifier()

    def recover(self, verifier=None):
        return RecoverPlansUseCase(
            store=self.store,
            clock=fixed_clock,
            notifier=self.notifier,
            verifier=verifier,
        ).execute()


class TestReportOnlyReadBack(Decision3Case):
    def test_verified_evidence_recorded_step_stays_blocked(self):
        self.store.save(plan_record([step_record()]))
        verifier = FakeVerifier(
            VerificationOutcome(
                verdict=Verdict.VERIFIED,
                channel="calendar_get",
                observed="الحدث موجود فعلًا بنفس العنوان والوقت",
            )
        )
        affected = self.recover(verifier)

        self.assertEqual(len(affected), 1)
        step = affected[0].steps[0]
        # The floor is untouched: blocked, unknown, awaiting off.
        self.assertIs(step.state, StepState.BLOCKED)
        self.assertIs(
            step.blocked_reason,
            BlockedReason.INTERRUPTED_UNKNOWN_OUTCOME,
        )
        self.assertTrue(step.outcome_unknown)
        self.assertIsNone(affected[0].awaiting_step_id)
        # The evidence is recorded, report-only.
        self.assertEqual(
            step.verify_outcome["verdict"], "verified"
        )
        self.assertIn("قراءة راجعة عند التعافي", step.error)
        self.assertIn("موجود فعلًا", step.error)
        # The verifier saw an empty result (recovery has none).
        self.assertEqual(verifier.calls, [("s1", {})])
        self.assertEqual(len(self.notifier.recovered_calls), 1)

    def test_unknown_evidence_worded_as_unresolved(self):
        self.store.save(plan_record([step_record()]))
        verifier = FakeVerifier(
            VerificationOutcome(
                verdict=Verdict.UNKNOWN,
                observed="تعذّرت القراءة الراجعة",
            )
        )
        affected = self.recover(verifier)
        step = affected[0].steps[0]
        self.assertIn("غير محسومة", step.error)
        self.assertTrue(step.outcome_unknown)

    def test_no_verifier_keeps_status_quo(self):
        self.store.save(plan_record([step_record()]))
        affected = self.recover(verifier=None)
        step = affected[0].steps[0]
        self.assertIs(step.state, StepState.BLOCKED)
        self.assertIsNone(step.error)
        self.assertIsNone(step.verify_outcome)

    def test_verifier_failure_never_breaks_recovery(self):
        self.store.save(plan_record([step_record()]))
        affected = self.recover(FakeVerifier(raises=True))
        step = affected[0].steps[0]
        self.assertIs(step.state, StepState.BLOCKED)
        self.assertIsNone(step.error)

    def test_approval_interrupted_step_gets_no_readback(self):
        pending = step_record(state="pending")
        self.store.save(plan_record([pending]))
        verifier = FakeVerifier(
            VerificationOutcome(verdict=Verdict.VERIFIED)
        )
        affected = self.recover(verifier)
        step = affected[0].steps[0]
        self.assertIs(
            step.blocked_reason,
            BlockedReason.APPROVAL_INTERRUPTED,
        )
        # Never dispatched => no effect to read back.
        self.assertEqual(verifier.calls, [])
        self.assertIsNone(step.error)

    def test_digest_carries_the_evidence_line(self):
        self.store.save(plan_record([step_record()]))
        verifier = FakeVerifier(
            VerificationOutcome(
                verdict=Verdict.FAILED,
                observed="لا حدث بهذا العنوان في ذلك اليوم",
            )
        )
        affected = self.recover(verifier)
        text = formatting.format_recovery(affected, NOW)
        self.assertIn("قراءة راجعة عند التعافي", text)
        self.assertIn("لا حدث بهذا العنوان", text)


class TestExactlyOnceAcrossProcesses(Decision3Case):
    def test_second_recovery_finds_nothing_and_stays_silent(self):
        self.store.save(plan_record([step_record()]))
        first = self.recover()
        second = self.recover()
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(self.notifier.recovered_calls), 1)


class TestCompensateRetired(Decision3Case):
    def test_field_is_gone_from_domain_and_record(self):
        self.assertNotIn(
            "compensate",
            {f.name for f in dataclasses.fields(PlanStep)},
        )
        self.assertNotIn(
            "compensate",
            {f.name for f in dataclasses.fields(PlanStepRecord)},
        )

    def test_legacy_record_with_compensate_loads_and_drops_key(self):
        record = plan_record([step_record(state="pending")])
        raw = record.to_dict()
        assert "compensate" not in raw["steps"][0]
        raw["steps"][0]["compensate"] = {"tool": "calendar_add"}
        path = Path(self._tmp.name) / "plans.json"
        path.write_text(
            json.dumps([raw], ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = self.store.get("p_d3")
        self.assertIsNotNone(loaded)
        self.assertNotIn("compensate", loaded.steps[0].to_dict())
        # And a re-save keeps it gone.
        self.store.save(loaded)
        reread = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("compensate", reread[0]["steps"][0])


_AGENT_CLS = None


def _agent_class():
    global _AGENT_CLS
    if _AGENT_CLS is None:
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.dotenv_values = lambda *a, **k: {}
        sys.modules.setdefault("dotenv", dotenv_stub)
        openai_stub = types.ModuleType("openai")

        class _OpenAIStub:
            def __init__(self, *a, **k):
                raise RuntimeError("openai stub: not usable")

        openai_stub.OpenAI = _OpenAIStub
        sys.modules.setdefault("openai", openai_stub)
        from core.agent import ALIXAgent

        _AGENT_CLS = ALIXAgent
    return _AGENT_CLS


class _FakeController:
    def __init__(self):
        self.recover_calls = 0

    def recover(self):
        self.recover_calls += 1
        return []


class TestBootEntry(unittest.TestCase):
    def test_recover_planning_at_boot_runs_once_per_instance(self):
        agent = _agent_class().__new__(_agent_class())
        agent._planning_recovered = False
        agent._planning_available = True
        controller = _FakeController()
        agent._ensure_planning_controller = lambda: controller
        agent.audit = lambda *a, **k: None

        agent.recover_planning_at_boot()
        agent.recover_planning_at_boot()
        self.assertEqual(controller.recover_calls, 1)


if __name__ == "__main__":
    unittest.main()
