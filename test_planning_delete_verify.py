"""delete_file read-back spec (2026-11-04, owner's ruling).

Decision 7's live acceptance (plan p_20261104T214934_17ca)
exposed a pre-existing Decision-2 gap: delete_file had NO
read-back spec, so a planned delete that had in fact
succeeded blocked VERIFICATION_UNKNOWN («لا مواصفة تحقق
للأداة delete_file») and escalated. The fix gives delete_file
a default spec on the calendar_delete pattern — verify_file
reports existence explicitly, checked as
``evidence.exists == False``.

The one plumbing subtlety: verify_file's ``ok`` is False
exactly when the file is absent (ok = exists and is_file in
the executor), so the decisive payload arrives as a FAILED
dispatch and the read-back gate would discard it. The spec
therefore declares ``evidence_on_failure`` — the only spec
that may — and the gate admits such a payload only when it
carries real evidence that actually reports every field
under evaluation. Everything else about the gate is
unchanged: failed payloads for all other channels stay
discarded, and an empty-evidence failure (a path the
channel may not inspect) stays UNKNOWN.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.entities import PlanStep
from domain.planning.states import PlanState, StepState

from features.planning.application.dto.planning import CreatePlanRequest
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.ports.verifier import Verdict
from features.planning.application.use_cases.create_plan import (
    CreatePlanUseCase,
)
from features.planning.application.use_cases.decompose_step import (
    DecomposeStepUseCase,
)
from features.planning.application.use_cases.run_plan import RunPlanUseCase
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)
from features.planning.infrastructure.adapters.readback_verifier import (
    ReadBackVerifier,
)

NOW = datetime(2026, 11, 4, 23, 0, tzinfo=timezone.utc)

LEVELS = {
    "read_file": "read",
    "write_file": "write",
    "verify_file": "read",
    "calendar_get": "read",
    "delete_file": "destructive",
    "calendar_delete": "destructive",
}
ALLOWLIST = frozenset({"delete_file"})
SCHEMAS = {"delete_file": frozenset({"path"})}
DESTRUCTIVE = frozenset({"delete_file"})


def fixed_clock():
    return NOW


def step(tool, args):
    return PlanStep(
        step_id="s", intent="x", tool=tool, args=args,
        state=StepState.PENDING, idempotency_key="p:s",
    )


def absent_payload(path="qa.txt"):
    """SafeExecutor.verify_file's exact shape for a missing
    file: ok False, existence reported in evidence."""
    return {
        "ok": False,
        "action": "verify_file",
        "message": "الملف غير موجود.",
        "evidence": {
            "path": path,
            "exists": False,
            "is_file": False,
            "size_bytes": 0,
            "verified": False,
        },
    }


def present_payload(path="qa.txt"):
    return {
        "ok": True,
        "action": "verify_file",
        "message": "تم التحقق من الملف.",
        "evidence": {
            "path": path,
            "exists": True,
            "is_file": True,
            "size_bytes": 12,
            "verified": True,
        },
    }


class FakeDispatch:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def execute(self, tool, args):
        self.calls.append((tool, args))
        return self.payload


class RaisingDispatch:
    def execute(self, tool, args):
        raise RuntimeError("channel down")


class TestDeleteFileReadBack(unittest.TestCase):
    def verify(self, payload, args=None):
        dispatch = FakeDispatch(payload)
        verifier = ReadBackVerifier(
            dispatch=dispatch, tool_levels=dict(LEVELS)
        )
        outcome = verifier.verify(
            step(
                "delete_file",
                {"path": "qa.txt"} if args is None else args,
            ),
            {"ok": True},
        )
        return outcome, dispatch

    def test_absent_file_verifies(self):
        outcome, dispatch = self.verify(absent_payload())
        self.assertEqual(outcome.verdict, Verdict.VERIFIED)
        self.assertEqual(outcome.channel, "verify_file")
        self.assertEqual(
            dispatch.calls, [("verify_file", {"path": "qa.txt"})]
        )

    def test_present_file_fails(self):
        outcome, _ = self.verify(present_payload())
        self.assertEqual(outcome.verdict, Verdict.FAILED)

    def test_present_as_directory_fails_not_unknown(self):
        # ok False (not a file) but existence positively
        # reported: the payload must reach evaluation and
        # contradict the delete, not be discarded.
        payload = present_payload()
        payload["ok"] = False
        payload["evidence"]["is_file"] = False
        payload["evidence"]["verified"] = False
        outcome, _ = self.verify(payload)
        self.assertEqual(outcome.verdict, Verdict.FAILED)

    def test_disallowed_path_empty_evidence_is_unknown(self):
        # The executor's not-allowed branch returns ok False
        # with NO evidence: absence cannot be proven for a
        # path the channel may not inspect.
        outcome, _ = self.verify(
            {"ok": False, "action": "verify_file",
             "message": "المسار غير مسموح.", "evidence": {}}
        )
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)

    def test_failure_without_evidence_key_is_unknown(self):
        outcome, _ = self.verify({"ok": False, "error": "x"})
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)

    def test_evidence_missing_checked_field_is_unknown(self):
        # Evidence present but existence not reported: the
        # channel did not answer the question under
        # evaluation, so the verdict is honest UNKNOWN,
        # never a fabricated FAILED.
        payload = absent_payload()
        del payload["evidence"]["exists"]
        outcome, _ = self.verify(payload)
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)

    def test_dispatch_exception_is_unknown(self):
        verifier = ReadBackVerifier(
            dispatch=RaisingDispatch(), tool_levels=dict(LEVELS)
        )
        outcome = verifier.verify(
            step("delete_file", {"path": "qa.txt"}), {"ok": True}
        )
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)

    def test_missing_path_has_no_spec(self):
        outcome, dispatch = self.verify(absent_payload(), args={})
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)
        self.assertIn("لا مواصفة", outcome.observed)
        self.assertEqual(dispatch.calls, [])

    def test_flag_is_scoped_to_the_delete_file_spec(self):
        # Regression guard: other channels' failed payloads
        # stay discarded even when they carry evidence —
        # write_file's spec declares no evidence_on_failure,
        # and neither does calendar_delete's.
        verifier = ReadBackVerifier(
            dispatch=FakeDispatch(absent_payload()),
            tool_levels=dict(LEVELS),
        )
        write_outcome = verifier.verify(
            step(
                "write_file",
                {"path": "qa.txt", "content": "نص"},
            ),
            {"ok": True},
        )
        self.assertEqual(write_outcome.verdict, Verdict.UNKNOWN)
        calendar_outcome = verifier.verify(
            step("calendar_delete", {"event_id": "e1"}),
            {"ok": True},
        )
        self.assertEqual(calendar_outcome.verdict, Verdict.UNKNOWN)

    def test_spec_index_and_probes(self):
        # Same discipline as test_planning_decision6: the
        # index must not drift from _spec_for's truth.
        self.assertIn(
            "delete_file", ReadBackVerifier.default_spec_tools()
        )
        verifier = ReadBackVerifier(
            dispatch=None, tool_levels=dict(LEVELS)
        )
        self.assertIsNotNone(
            verifier._spec_for(
                step("delete_file", {"path": "x"}), {}
            )
        )
        self.assertIsNone(
            verifier._spec_for(step("delete_file", {}), {})
        )


class FakePlanner(PlannerPort):
    def __init__(self, plan_draft=None):
        self._plan_draft = plan_draft or {"steps": []}
        self.decompose_calls = 0

    def plan(self, goal, prior_actions, context):
        return self._plan_draft

    def decompose(self, goal, failed_step, remaining_steps):
        self.decompose_calls += 1
        return {"mode": "give_up"}


class RouterDispatch(ToolDispatchPort):
    """Serves the step's own execution and the verifier's
    read-back from per-tool scripted payloads."""

    def __init__(self, payloads):
        self._payloads = dict(payloads)
        self.calls = []

    def execute(self, tool, args, consent_digest=None):
        self.calls.append(tool)
        return self._payloads[tool]


class RecordingNotifier:
    def __init__(self):
        self.escalated_calls = []
        self.finished_calls = []

    def created(self, plan, approval_steps):
        pass

    def decomposed(self, plan, failed_step, new_step_ids):
        pass

    def escalated(self, plan, failed_step, reason):
        self.escalated_calls.append((plan.plan_id, reason))

    def finished(self, plan):
        self.finished_calls.append(plan.plan_id)

    def recovered(self, plans):
        pass


class TestDeleteVerificationInRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(Path(self._tmp.name) / "plans.json")
        self.notifier = RecordingNotifier()
        self.planner = FakePlanner(
            {"steps": [{
                "intent": "احذف الملف",
                "tool": "delete_file",
                "args": {"path": "qa.txt"},
            }]}
        )

    def run_delete_plan(self, verify_payload):
        create = CreatePlanUseCase(
            planner=self.planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=DESTRUCTIVE,
            confirming_tools=DESTRUCTIVE,
            clock=fixed_clock,
            notifier=self.notifier,
        )
        outcome = create.execute(
            CreatePlanRequest(goal="هدف", origin="interactive")
        )
        assert outcome.created, outcome
        plan = outcome.plan
        router = RouterDispatch({
            "delete_file": {"ok": True, "message": "تم الحذف"},
            "verify_file": verify_payload,
        })
        verifier = ReadBackVerifier(
            dispatch=router, tool_levels=dict(LEVELS)
        )
        decompose = DecomposeStepUseCase(
            planner=self.planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=DESTRUCTIVE,
            clock=fixed_clock,
            notifier=self.notifier,
        )
        run = RunPlanUseCase(
            dispatch=router,
            verifier=verifier,
            store=self.store,
            decompose=decompose,
            clock=fixed_clock,
            notifier=self.notifier,
            destructive_tools=DESTRUCTIVE,
        )
        return run.execute(plan), plan

    def test_verified_delete_completes_the_plan(self):
        # Tonight's live incident, inverted: the delete's
        # read-back proves absence, so the step SUCCEEDS
        # instead of blocking VERIFICATION_UNKNOWN.
        outcome, plan = self.run_delete_plan(absent_payload())
        self.assertIs(outcome.state, PlanState.DONE)
        self.assertEqual(plan.steps[0].state, StepState.SUCCEEDED)
        self.assertEqual(self.notifier.finished_calls, [plan.plan_id])
        self.assertEqual(self.notifier.escalated_calls, [])

    def test_contradicted_delete_escalates_without_replan(self):
        # The file is still there: FAILED verdict, direct
        # escalation per Decision 2 — never a decompose.
        outcome, plan = self.run_delete_plan(present_payload())
        self.assertIs(outcome.state, PlanState.ESCALATED)
        # Decision 2 semantics: a positively disproven effect
        # FAILS the step (only UNKNOWN blocks outcome_unknown).
        self.assertEqual(plan.steps[0].state, StepState.FAILED)
        self.assertIn("فشل التحقق", plan.steps[0].error)
        self.assertEqual(len(self.notifier.escalated_calls), 1)
        self.assertEqual(self.planner.decompose_calls, 0)


if __name__ == "__main__":
    unittest.main()
