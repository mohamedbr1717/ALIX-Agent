"""Decision 7 — destructive-step consent (owner's split ruling,
2026-11-04): an interactive destructive step whose concrete
(tool, args) the accepted draft fixed executes UNDER the plan
approval (digest-enforced); anything else — drift, a step born
after acceptance, a never-inherit tool — faces its own card at
execution; scheduled destructive steps stay born BLOCKED.

The dispatch fake below is a faithful miniature of the production
pipeline's confirmation gate (same order: consent verification,
then the per-call card, then the body, with the byte-pinned
denial result). The REAL pipeline gate is exercised directly in
TestPipelineConsentGate through the mixin harness.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.planning.consent import (
    CONSENT_EXEC_CARD,
    CONSENT_PLAN_CARD,
    consent_digest_for,
)
from domain.planning.entities import Plan, PlanStep
from domain.planning.states import BlockedReason, PlanState, StepState

from features.planning.application.dto.planning import (
    CreatePlanRequest,
    PlanStepRecord,
)
from features.planning.application.mapping import (
    plan_to_record,
    record_to_plan,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.use_cases.create_plan import (
    CreatePlanUseCase,
)
from features.planning.application.use_cases.decompose_step import (
    DecomposeStepUseCase,
)
from features.planning.application.use_cases.run_plan import (
    APPROVAL_DENIED_ERROR_PREFIX,
    RunPlanUseCase,
)
from features.planning.infrastructure.adapters.contract_ok_verifier import (
    ContractOkVerifier,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat(timespec="seconds")

LEVELS = {
    "read_file": "read",
    "write_file": "write",
    "delete_file": "destructive",
    "calendar_delete": "destructive",
    "phone_call": "destructive",
    "send_sms": "destructive",
}
ALLOWLIST = frozenset(LEVELS)
SCHEMAS = {
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
    "delete_file": frozenset({"path"}),
    "calendar_delete": frozenset({"event_id"}),
    "phone_call": frozenset({"number"}),
    "send_sms": frozenset({"number", "message"}),
}
DESTRUCTIVE = frozenset(
    name for name, level in LEVELS.items() if level == "destructive"
)
CONFIRMING_TOOLS = frozenset(
    name
    for name, level in LEVELS.items()
    if level in ("write", "execute", "destructive")
)

#: Same shape the production pipeline returns on a confirmation
#: denial (the executor pins the prefix contract separately).
DENIAL_RESULT = {
    "ok": False,
    "error": (
        APPROVAL_DENIED_ERROR_PREFIX
        + " تنفيذ العملية. أُلغيت نهائيًا."
    ),
}


def fixed_clock():
    return NOW


def draft_step(tool, intent="خطوة", args=None):
    return {
        "intent": intent,
        "tool": tool,
        "args": args if args is not None else {},
    }


class FakePlanner(PlannerPort):
    def __init__(self, plan_draft=None, decompose_script=()):
        self._plan_draft = plan_draft or {"steps": []}
        self._decompose_script = list(decompose_script)
        self.plan_calls = 0
        self.decompose_calls = 0

    def plan(self, goal, prior_actions, context):
        self.plan_calls += 1
        return self._plan_draft

    def decompose(self, goal, failed_step, remaining_steps):
        self.decompose_calls += 1
        if self._decompose_script:
            return self._decompose_script.pop(0)
        return {"mode": "give_up"}


class ConsentAwareDispatch(ToolDispatchPort):
    """Miniature of the production gate: a confirming tool faces
    the scripted confirmer UNLESS a presented consent digest
    recomputes over (tool, args) for a destructive tool with no
    stricter per-call rule — the production rule, restated here
    so the slice's half of the contract is pinned independently
    of the pipeline's half (TestPipelineConsentGate)."""

    def __init__(self, confirmer, fail_tools=frozenset()):
        self._confirmer = confirmer
        self._fail_tools = set(fail_tools)
        self.calls = []       # (tool, args, consent_digest)
        self.card_calls = []  # tools that actually faced the card
        self.executed = []    # post-confirmation body runs

    def execute(self, tool, args, consent_digest=None):
        self.calls.append((tool, dict(args), consent_digest))
        if tool in self._fail_tools:
            self._fail_tools.discard(tool)
            return {"ok": False, "error": "فشل مُهندَس للاختبار"}
        if LEVELS[tool] in ("write", "execute", "destructive"):
            consented = (
                consent_digest is not None
                and LEVELS[tool] == "destructive"
                and tool not in ("phone_call", "send_sms")
                and consent_digest
                == consent_digest_for(tool, args)
            )
            if not consented:
                self.card_calls.append(tool)
                if not self._confirmer(tool, args):
                    return dict(DENIAL_RESULT)
        self.executed.append(tool)
        return {"ok": True, "message": f"تم {tool}"}


class RecordingNotifier:
    def __init__(self):
        self.created_calls = []
        self.decomposed_calls = []
        self.escalated_calls = []
        self.finished_calls = []

    def created(self, plan, approval_steps):
        self.created_calls.append((plan.plan_id, approval_steps))

    def decomposed(self, plan, failed_step, new_step_ids):
        self.decomposed_calls.append(
            (failed_step.step_id, list(new_step_ids))
        )

    def escalated(self, plan, failed_step, reason):
        self.escalated_calls.append((plan.plan_id, reason))

    def finished(self, plan):
        self.finished_calls.append(plan.plan_id)

    def recovered(self, plans):
        pass


class Decision7Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.notifier = RecordingNotifier()

    def create(self, draft, origin="interactive", planner=None):
        planner = planner or FakePlanner(plan_draft=draft)
        use_case = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=DESTRUCTIVE,
            confirming_tools=CONFIRMING_TOOLS,
            clock=fixed_clock,
            notifier=self.notifier,
        )
        outcome = use_case.execute(
            CreatePlanRequest(goal="هدف", origin=origin)
        )
        assert outcome.created, outcome
        return outcome.plan

    def build_run(self, dispatch, planner=None):
        planner = planner or FakePlanner()
        decompose = DecomposeStepUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=DESTRUCTIVE,
            clock=fixed_clock,
            notifier=self.notifier,
        )
        return RunPlanUseCase(
            dispatch=dispatch,
            verifier=ContractOkVerifier(),
            store=self.store,
            decompose=decompose,
            clock=fixed_clock,
            notifier=self.notifier,
            destructive_tools=DESTRUCTIVE,
        )


class TestStamping(Decision7Case):
    def test_interactive_destructive_step_is_stamped(self):
        plan = self.create(
            {"steps": [draft_step(
                "delete_file", "احذف الملف", {"path": "x"})]}
        )
        step = plan.steps[0]
        self.assertEqual(step.consent_source, CONSENT_PLAN_CARD)
        self.assertEqual(
            step.consent_digest,
            consent_digest_for("delete_file", {"path": "x"}),
        )
        # The creation notice must not promise a card that the
        # stamped step will never face.
        self.assertEqual(
            self.notifier.created_calls, [(plan.plan_id, 0)]
        )

    def test_write_step_is_not_stamped_and_still_counts(self):
        plan = self.create(
            {"steps": [draft_step(
                "write_file", "اكتب",
                {"path": "x", "content": "y"})]}
        )
        step = plan.steps[0]
        self.assertIsNone(step.consent_digest)
        self.assertIsNone(step.consent_source)
        self.assertEqual(
            self.notifier.created_calls, [(plan.plan_id, 1)]
        )

    def test_phone_tools_are_never_stamped(self):
        plan = self.create(
            {"steps": [draft_step(
                "phone_call", "اتصل", {"number": "+212600000000"})]}
        )
        step = plan.steps[0]
        self.assertIsNone(step.consent_digest)
        self.assertIsNone(step.consent_source)
        self.assertEqual(
            self.notifier.created_calls, [(plan.plan_id, 1)]
        )

    def test_scheduled_destructive_step_born_blocked_unstamped(self):
        plan = self.create(
            {"steps": [draft_step(
                "delete_file", "احذف", {"path": "x"})]},
            origin="scheduled",
        )
        step = plan.steps[0]
        self.assertIs(step.state, StepState.BLOCKED)
        self.assertIs(
            step.blocked_reason, BlockedReason.SCHEDULED_POLICY
        )
        self.assertIsNone(step.consent_digest)
        self.assertIsNone(step.consent_source)


class TestExecutionConsent(Decision7Case):
    def test_stamped_step_executes_without_facing_a_card(self):
        plan = self.create(
            {"steps": [draft_step(
                "delete_file", "احذف", {"path": "x"})]}
        )
        # The confirmer DENIES everything: if a card were faced,
        # the step could not execute at all.
        dispatch = ConsentAwareDispatch(lambda tool, args: False)
        outcome = self.build_run(dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        self.assertEqual(dispatch.card_calls, [])
        self.assertEqual(dispatch.executed, ["delete_file"])
        self.assertEqual(
            dispatch.calls[0][2],
            consent_digest_for("delete_file", {"path": "x"}),
        )
        step = plan.steps[0]
        self.assertIs(step.state, StepState.SUCCEEDED)
        self.assertEqual(step.consent_source, CONSENT_PLAN_CARD)

    def test_args_drift_revokes_inheritance(self):
        plan = self.create(
            {"steps": [draft_step(
                "delete_file", "احذف", {"path": "x"})]}
        )
        # Runtime materialization: the args that will actually
        # run are NOT the args the draft fixed.
        plan.steps[0].args = {"path": "y"}
        self.store.save(plan_to_record(plan, NOW))
        dispatch = ConsentAwareDispatch(lambda tool, args: True)
        outcome = self.build_run(dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        # No consent was presented; the step faced its own card.
        self.assertIsNone(dispatch.calls[0][2])
        self.assertEqual(dispatch.card_calls, ["delete_file"])
        # And the consent that actually authorized it is recorded.
        self.assertEqual(
            plan.steps[0].consent_source, CONSENT_EXEC_CARD
        )

    def test_unstamped_step_faces_its_own_card(self):
        plan = Plan(
            plan_id="p_manual7",
            goal="هدف",
            origin="interactive",
            steps=[
                PlanStep(
                    step_id="s1",
                    intent="احذف",
                    tool="delete_file",
                    args={"path": "x"},
                    idempotency_key="p_manual7:s1",
                    created_at=NOW_ISO,
                    updated_at=NOW_ISO,
                )
            ],
            created_at=NOW_ISO,
            updated_at=NOW_ISO,
            expires_at=iso_future(),
        )
        self.store.save(plan_to_record(plan, NOW))
        dispatch = ConsentAwareDispatch(lambda tool, args: True)
        outcome = self.build_run(dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        self.assertIsNone(dispatch.calls[0][2])
        self.assertEqual(dispatch.card_calls, ["delete_file"])
        self.assertEqual(
            plan.steps[0].consent_source, CONSENT_EXEC_CARD
        )

    def test_exec_card_denial_blocks_and_body_never_runs(self):
        plan = Plan(
            plan_id="p_manual8",
            goal="هدف",
            origin="interactive",
            steps=[
                PlanStep(
                    step_id="s1",
                    intent="احذف",
                    tool="delete_file",
                    args={"path": "x"},
                    idempotency_key="p_manual8:s1",
                    created_at=NOW_ISO,
                    updated_at=NOW_ISO,
                ),
                PlanStep(
                    step_id="s2",
                    intent="اقرأ",
                    tool="read_file",
                    args={"path": "x"},
                    idempotency_key="p_manual8:s2",
                    created_at=NOW_ISO,
                    updated_at=NOW_ISO,
                ),
            ],
            created_at=NOW_ISO,
            updated_at=NOW_ISO,
            expires_at=iso_future(),
        )
        self.store.save(plan_to_record(plan, NOW))
        dispatch = ConsentAwareDispatch(lambda tool, args: False)
        outcome = self.build_run(dispatch).execute(plan)
        self.assertEqual(outcome.stopped_reason, "approval_denied")
        step = plan.steps[0]
        self.assertIs(step.state, StepState.BLOCKED)
        self.assertIs(
            step.blocked_reason, BlockedReason.APPROVAL_DENIED
        )
        # The destructive body never ran, the next step never
        # dispatched, and a denial records no consent.
        self.assertEqual(dispatch.executed, [])
        self.assertEqual(len(dispatch.calls), 1)
        self.assertIsNone(step.consent_source)

    def test_decomposition_born_step_faces_its_own_card(self):
        planner = FakePlanner(
            plan_draft={"steps": [draft_step(
                "read_file", "اقرأ", {"path": "x"})]},
            decompose_script=[
                {"mode": "decompose", "steps": [draft_step(
                    "delete_file", "احذف بدلًا", {"path": "x"})]}
            ],
        )
        plan = self.create(None, planner=planner)
        dispatch = ConsentAwareDispatch(
            lambda tool, args: True, fail_tools={"read_file"}
        )
        outcome = self.build_run(
            dispatch, planner=planner
        ).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        self.assertEqual(dispatch.card_calls, ["delete_file"])
        sub = plan.step("s1.1")
        self.assertIsNone(sub.consent_digest)
        self.assertEqual(sub.consent_source, CONSENT_EXEC_CARD)

    def test_scheduled_plan_never_dispatches_destructive(self):
        plan = self.create(
            {"steps": [draft_step(
                "delete_file", "احذف", {"path": "x"})]},
            origin="scheduled",
        )
        dispatch = ConsentAwareDispatch(lambda tool, args: True)
        self.build_run(dispatch).execute(plan)
        self.assertEqual(dispatch.calls, [])


class TestPhoneTools(Decision7Case):
    def test_phone_call_faces_its_card_inside_a_plan(self):
        plan = self.create(
            {"steps": [draft_step(
                "phone_call", "اتصل", {"number": "+212600000000"})]}
        )
        dispatch = ConsentAwareDispatch(lambda tool, args: True)
        outcome = self.build_run(dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        self.assertIsNone(dispatch.calls[0][2])
        self.assertEqual(dispatch.card_calls, ["phone_call"])
        self.assertEqual(
            plan.steps[0].consent_source, CONSENT_EXEC_CARD
        )


class TestPersistence(Decision7Case):
    def test_consent_fields_survive_the_store_round_trip(self):
        plan = self.create(
            {"steps": [draft_step(
                "delete_file", "احذف", {"path": "x"})]}
        )
        record = self.store.get(plan.plan_id)
        self.assertEqual(
            record.steps[0].consent_source, CONSENT_PLAN_CARD
        )
        self.assertEqual(
            record.steps[0].consent_digest,
            consent_digest_for("delete_file", {"path": "x"}),
        )
        loaded = record_to_plan(record, NOW)
        self.assertEqual(
            loaded.steps[0].consent_digest,
            record.steps[0].consent_digest,
        )
        self.assertEqual(
            loaded.steps[0].consent_source, CONSENT_PLAN_CARD
        )

    def test_legacy_record_without_consent_keys_loads_unstamped(self):
        record = PlanStepRecord.from_dict(
            {
                "step_id": "s1",
                "intent": "قديمة",
                "tool": "delete_file",
                "args": {"path": "x"},
                "state": "pending",
                "idempotency_key": "p_old:s1",
            }
        )
        self.assertIsNone(record.consent_digest)
        self.assertIsNone(record.consent_source)


def iso_future():
    return (NOW + timedelta(hours=24)).isoformat(
        timespec="seconds"
    )


# ---------------------------------------------------------------
# The REAL pipeline gate (core/agent/_tool_pipeline.py), driven
# through a bare mixin instance with a stub Policy. The module's
# third-party leaves (dotenv, openai) are absent in some dev
# environments; they are stubbed ONLY when the real import fails,
# so on the owner's machines the genuine module is exercised.
# ---------------------------------------------------------------


def _load_pipeline_mixin():
    try:
        from core.agent._tool_pipeline import _ToolPipelineMixin

        return _ToolPipelineMixin
    except ModuleNotFoundError:
        import sys
        import types

        for _ in range(10):
            try:
                from core.agent._tool_pipeline import (
                    _ToolPipelineMixin,
                )

                return _ToolPipelineMixin
            except ModuleNotFoundError as exc:
                stub = types.ModuleType(exc.name)
                stub.dotenv_values = lambda *a, **k: {}
                stub.load_dotenv = lambda *a, **k: None
                stub.OpenAI = object
                stub.AsyncOpenAI = object
                sys.modules[exc.name] = stub
        raise unittest.SkipTest(
            "pipeline module not importable in this environment"
        )


class _StubPolicy:
    SCHEDULER_DENIED_TOOLS = frozenset({"phone_call"})

    def __init__(
        self, levels, scheduled_mode=False, permitted=False
    ):
        self._levels = levels
        self.scheduled_mode = scheduled_mode
        self._permitted = permitted

    def tool_permission(self, name):
        return self._levels.get(name)

    def requires_confirmation(self, name):
        return self._levels.get(name) in (
            "write",
            "execute",
            "destructive",
        )

    def scheduled_tool_permitted(self, name):
        return self._permitted


class TestPipelineConsentGate(unittest.TestCase):
    def _gate(self, levels, confirmer, **policy_kwargs):
        mixin_cls = _load_pipeline_mixin()
        gate = mixin_cls.__new__(mixin_cls)
        gate.policy = _StubPolicy(levels, **policy_kwargs)
        gate.audits = []
        gate.audit = lambda event, data, **kw: gate.audits.append(
            (event, data)
        )
        gate.confirm_calls = []
        gate.confirm_fn = lambda name, args, level: (
            gate.confirm_calls.append(name), confirmer
        )[1]
        return gate

    def test_valid_digest_confirms_without_a_card(self):
        gate = self._gate(
            {"delete_file": "destructive"}, confirmer=False
        )
        digest = consent_digest_for(
            "delete_file", {"path": "x"}
        )
        approved = gate.confirm_tool(
            "delete_file", {"path": "x"}, digest
        )
        self.assertTrue(approved)
        self.assertEqual(gate.confirm_calls, [])
        self.assertEqual(
            gate.audits[0][0], "tool_confirmation_plan_consent"
        )

    def test_wrong_digest_falls_back_to_the_card(self):
        gate = self._gate(
            {"delete_file": "destructive"}, confirmer=True
        )
        approved = gate.confirm_tool(
            "delete_file", {"path": "x"}, "0" * 64
        )
        self.assertTrue(approved)
        self.assertEqual(gate.confirm_calls, ["delete_file"])
        self.assertEqual(
            gate.audits[0][0],
            "tool_confirmation_plan_consent_rejected",
        )

    def test_digest_for_other_args_does_not_confirm(self):
        gate = self._gate(
            {"delete_file": "destructive"}, confirmer=False
        )
        digest = consent_digest_for(
            "delete_file", {"path": "x"}
        )
        approved = gate.confirm_tool(
            "delete_file", {"path": "y"}, digest
        )
        self.assertFalse(approved)
        self.assertEqual(gate.confirm_calls, ["delete_file"])

    def test_write_level_digest_is_not_honored(self):
        gate = self._gate(
            {"write_file": "write"}, confirmer=False
        )
        digest = consent_digest_for(
            "write_file", {"path": "x", "content": "y"}
        )
        approved = gate.confirm_tool(
            "write_file", {"path": "x", "content": "y"}, digest
        )
        self.assertFalse(approved)
        self.assertEqual(gate.confirm_calls, ["write_file"])

    def test_phone_call_digest_is_never_honored(self):
        gate = self._gate(
            {"phone_call": "destructive"}, confirmer=False
        )
        digest = consent_digest_for(
            "phone_call", {"number": "+212600000000"}
        )
        approved = gate.confirm_tool(
            "phone_call", {"number": "+212600000000"}, digest
        )
        self.assertFalse(approved)
        self.assertEqual(gate.confirm_calls, ["phone_call"])

    def test_scheduled_branch_precedes_consent(self):
        gate = self._gate(
            {"phone_call": "destructive"},
            confirmer=True,
            scheduled_mode=True,
            permitted=False,
        )
        digest = consent_digest_for(
            "phone_call", {"number": "+212600000000"}
        )
        approved = gate.confirm_tool(
            "phone_call", {"number": "+212600000000"}, digest
        )
        # Hard-denied by the scheduled branch: no consent, no card.
        self.assertFalse(approved)
        self.assertEqual(gate.confirm_calls, [])


if __name__ == "__main__":
    unittest.main()
