"""Step-output binding (2026-11-06, owner's ruling — option ج).

Live root: the 2026-11-06 plan for Amazon 11/11 picks reported
✅✅✅ while its deliverable file contained the literal sentence
«[سيتم استخراج البيانات من الخطوة السابقة]» — step args are
frozen at draft time and the executor had no way to carry a
value from one step to the next, so the planner's promissory
placeholder sailed through (the 82a1063 guard rejects only
``{{...}}`` template syntax). This suite pins the governed
capability that replaces the promise:

- exactly one legal form, {{steps.sN.output}}, referencing an
  EARLIER step of the same draft — validated at acceptance,
  rejected whole otherwise (binding_invalid), with every other
  {{...}} form still placeholder_args;
- bindings are banned in decomposition drafts (v1 scope);
- a bound step is never consent-stamped (Decision 7: args
  materialized after approval face their own card), and the
  card's dispatch carries the MATERIALIZED args;
- resolution at dispatch is fail-closed: a missing/failed
  source output blocks the step (BINDING_UNAVAILABLE) without
  dispatching — never a literal token, never an empty string;
- verification judges the materialized args, not the tokens;
- captured outputs persist through the store, so a resumed
  plan can still resolve its bindings.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.binding import (
    MAX_RESOLVED_ARG_CHARS,
    find_bindings,
    resolve_args,
    step_uses_bindings,
)
from domain.planning.consent import (
    CONSENT_EXEC_CARD,
    consent_digest_for,
)
from domain.planning.entities import Plan, PlanStep
from domain.planning.states import BlockedReason, PlanState, StepState
from domain.planning.validation import (
    PlanRejected,
    validate_plan_draft,
    validate_step_list,
)

from features.planning.application.dto.planning import CreatePlanRequest
from features.planning.application.mapping import record_to_plan
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.ports.verifier import (
    VerificationOutcome,
    Verdict,
    VerifierPort,
)
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

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

LEVELS = {
    "web_search": "read",
    "web_fetch": "read",
    "read_file": "read",
    "notify": "read",
    "write_file": "write",
    "delete_file": "destructive",
}
ALLOWLIST = frozenset(LEVELS)
SCHEMAS = {
    "web_search": frozenset({"query"}),
    "web_fetch": frozenset({"url"}),
    "read_file": frozenset({"path"}),
    "notify": frozenset({"text", "meta"}),
    "write_file": frozenset({"path", "content"}),
    "delete_file": frozenset({"path"}),
}
DESTRUCTIVE = frozenset({"delete_file"})
CONFIRMING = frozenset({"delete_file"})

SEARCH_TEXT = "منتج أ — منتج ب"


def fixed_clock():
    return NOW


def draft(*steps):
    return {"steps": list(steps)}


def step_draft(tool, args, intent="خطوة"):
    return {"intent": intent, "tool": tool, "args": args}


class FakePlanner(PlannerPort):
    def __init__(self, plan_draft=None, decompose_draft=None):
        self._plan_draft = plan_draft or {"steps": []}
        self._decompose_draft = decompose_draft or {
            "mode": "give_up"
        }
        self.decompose_calls = 0

    def plan(self, goal, prior_actions, context):
        return self._plan_draft

    def decompose(self, goal, failed_step, remaining_steps):
        self.decompose_calls += 1
        return self._decompose_draft


class CapturingDispatch(ToolDispatchPort):
    """Per-tool scripted payloads; records exactly what the
    executor sent, including the consent parameter."""

    def __init__(self, payloads):
        self._payloads = dict(payloads)
        self.calls = []

    def execute(self, tool, args, consent_digest=None):
        self.calls.append((tool, dict(args), consent_digest))
        payload = self._payloads[tool]
        if callable(payload):
            return payload(args)
        return payload

    def calls_for(self, tool):
        return [c for c in self.calls if c[0] == tool]


class AlwaysVerified(VerifierPort):
    def verify(self, step, result):
        return VerificationOutcome(
            verdict=Verdict.VERIFIED, channel="contract"
        )


class RecordingNotifier:
    def __init__(self):
        self.created_calls = []
        self.escalated_calls = []
        self.finished_calls = []

    def created(self, plan, approval_steps):
        self.created_calls.append((plan.plan_id, approval_steps))

    def decomposed(self, plan, failed_step, new_step_ids):
        pass

    def escalated(self, plan, failed_step, reason):
        self.escalated_calls.append((plan.plan_id, reason))

    def finished(self, plan):
        self.finished_calls.append(plan.plan_id)

    def clarification(self, *args, **kwargs):
        pass

    def recovered(self, plans):
        pass


class BindingHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.notifier = RecordingNotifier()

    def create_plan(self, plan_draft, planner=None):
        planner = planner or FakePlanner(plan_draft)
        create = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=DESTRUCTIVE,
            confirming_tools=CONFIRMING,
            clock=fixed_clock,
            notifier=self.notifier,
        )
        outcome = create.execute(
            CreatePlanRequest(goal="هدف", origin="interactive")
        )
        assert outcome.created, outcome
        return outcome.plan

    def make_run(self, dispatch, verifier=None, planner=None):
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
            verifier=verifier or AlwaysVerified(),
            store=self.store,
            decompose=decompose,
            clock=fixed_clock,
            notifier=self.notifier,
            destructive_tools=DESTRUCTIVE,
        )


class TestBindingValidation(unittest.TestCase):
    def validate(self, plan_draft):
        return validate_plan_draft(
            plan_draft, ALLOWLIST, SCHEMAS
        )

    def test_legal_reference_accepted(self):
        result = self.validate(draft(
            step_draft("web_search", {"query": "أحذية"}),
            step_draft("write_file", {
                "path": "out.txt",
                "content": "النتيجة: {{steps.s1.output}}",
            }),
        ))
        self.assertNotIsInstance(result, PlanRejected)
        self.assertEqual(len(result), 2)

    def test_self_reference_rejected(self):
        result = self.validate(draft(
            step_draft("write_file", {
                "path": "out.txt",
                "content": "{{steps.s1.output}}",
            }),
        ))
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "binding_invalid")

    def test_forward_reference_rejected(self):
        result = self.validate(draft(
            step_draft("write_file", {
                "path": "out.txt",
                "content": "{{steps.s2.output}}",
            }),
            step_draft("web_search", {"query": "x"}),
        ))
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "binding_invalid")

    def test_unknown_reference_rejected(self):
        result = self.validate(draft(
            step_draft("web_search", {"query": "x"}),
            step_draft("write_file", {
                "path": "out.txt",
                "content": "{{steps.s7.output}}",
            }),
        ))
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "binding_invalid")

    def test_old_template_still_placeholder_rejected(self):
        # Regression (82a1063): the 2026-11-01 incident form
        # stays rejected with its original reason.
        result = self.validate(draft(
            step_draft("web_search", {"query": "ذهب"}),
            step_draft("write_file", {
                "path": "gold.txt",
                "content": "{{step.result.0.content}}",
            }),
        ))
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "placeholder_args")

    def test_mixed_legal_and_illegal_template_rejected(self):
        result = self.validate(draft(
            step_draft("web_search", {"query": "x"}),
            step_draft("write_file", {
                "path": "out.txt",
                "content": "{{steps.s1.output}} ثم {{أي شيء}}",
            }),
        ))
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "placeholder_args")

    def test_multiple_and_nested_bindings_accepted(self):
        result = self.validate(draft(
            step_draft("web_search", {"query": "أ"}),
            step_draft("web_search", {"query": "ب"}),
            step_draft("notify", {
                "text": "{{steps.s1.output}} / {{steps.s2.output}}",
                "meta": {"echo": ["{{steps.s1.output}}"]},
            }),
        ))
        self.assertNotIsInstance(result, PlanRejected)
        self.assertEqual(len(result), 3)

    def test_decompose_drafts_reject_bindings(self):
        result = validate_step_list(
            [
                step_draft("web_search", {"query": "x"}),
                step_draft("write_file", {
                    "path": "out.txt",
                    "content": "{{steps.s1.output}}",
                }),
            ],
            ALLOWLIST,
            SCHEMAS,
            max_steps=4,
            allow_bindings=False,
        )
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "binding_invalid")


class TestBindingDomain(unittest.TestCase):
    def test_find_and_resolve(self):
        args = {"content": "أ: {{steps.s1.output}}"}
        self.assertEqual(find_bindings(args), ["s1"])
        self.assertTrue(step_uses_bindings(args))
        resolved = resolve_args(args, {"s1": "قيمة"})
        self.assertEqual(resolved, {"content": "أ: قيمة"})
        # The source dict is never mutated.
        self.assertEqual(
            args, {"content": "أ: {{steps.s1.output}}"}
        )


class TestBindingCreation(BindingHarness):
    def test_bound_destructive_step_is_never_stamped(self):
        plan = self.create_plan(draft(
            step_draft("web_search", {"query": "ملف مؤقت"}),
            step_draft("delete_file", {
                "path": "{{steps.s1.output}}",
            }),
        ))
        bound = plan.steps[1]
        self.assertIsNone(bound.consent_digest)
        self.assertIsNone(bound.consent_source)
        # The creation notice must promise the card that WILL
        # come: the bound step counts as an approval step.
        self.assertEqual(
            self.notifier.created_calls, [(plan.plan_id, 1)]
        )

    def test_unbound_destructive_step_still_stamped(self):
        # Decision 7 control: literal args keep plan consent.
        plan = self.create_plan(draft(
            step_draft("delete_file", {"path": "x.txt"}),
        ))
        only = plan.steps[0]
        self.assertEqual(
            only.consent_digest,
            consent_digest_for("delete_file", {"path": "x.txt"}),
        )
        self.assertEqual(
            self.notifier.created_calls, [(plan.plan_id, 0)]
        )


class TestBindingExecution(BindingHarness):
    def test_materialized_args_reach_dispatch(self):
        plan = self.create_plan(draft(
            step_draft("web_search", {"query": "منتجات"}),
            step_draft("write_file", {
                "path": "out.txt",
                "content": "القائمة: {{steps.s1.output}}",
            }),
        ))
        dispatch = CapturingDispatch({
            "web_search": {"ok": True, "message": SEARCH_TEXT},
            "write_file": {"ok": True, "message": "تمت الكتابة"},
        })
        outcome = self.make_run(dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)

        write_calls = dispatch.calls_for("write_file")
        self.assertEqual(len(write_calls), 1)
        _, sent_args, sent_consent = write_calls[0]
        self.assertEqual(
            sent_args,
            {
                "path": "out.txt",
                "content": f"القائمة: {SEARCH_TEXT}",
            },
        )
        self.assertIsNone(sent_consent)

        first, second = plan.steps
        self.assertEqual(first.output_text, SEARCH_TEXT)
        # The audit answers "what actually ran".
        self.assertEqual(
            second.resolved_args_hash,
            consent_digest_for("write_file", sent_args),
        )
        # The stored args keep the intent (the token).
        self.assertEqual(
            second.args["content"],
            "القائمة: {{steps.s1.output}}",
        )
        self.assertEqual(second.state, StepState.SUCCEEDED)

    def test_bound_destructive_dispatch_records_exec_card(self):
        plan = self.create_plan(draft(
            step_draft("web_search", {"query": "مسار"}),
            step_draft("delete_file", {
                "path": "{{steps.s1.output}}",
            }),
        ))
        dispatch = CapturingDispatch({
            "web_search": {"ok": True, "message": "tmp.txt"},
            "delete_file": {"ok": True, "message": "تم الحذف"},
        })
        outcome = self.make_run(dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        delete_calls = dispatch.calls_for("delete_file")
        self.assertEqual(len(delete_calls), 1)
        _, sent_args, sent_consent = delete_calls[0]
        self.assertEqual(sent_args, {"path": "tmp.txt"})
        # No plan consent was claimed — the pipeline's own card
        # authorized this call, and the step records that.
        self.assertIsNone(sent_consent)
        self.assertEqual(
            plan.steps[1].consent_source, CONSENT_EXEC_CARD
        )

    def _direct_plan(self, first_step, bound_args):
        steps = [
            first_step,
            PlanStep(
                step_id="s2",
                intent="اكتب",
                tool="write_file",
                args=bound_args,
                state=StepState.PENDING,
                idempotency_key="p_test:s2",
            ),
        ]
        return Plan(
            plan_id="p_test",
            goal="هدف",
            origin="interactive",
            steps=steps,
            prior_actions=[],
            replans_used=0,
            awaiting_step_id=None,
            escalated=False,
            created_at="2026-11-06T12:00:00+00:00",
            updated_at="2026-11-06T12:00:00+00:00",
            expires_at="2026-11-07T12:00:00+00:00",
        )

    def test_missing_output_blocks_without_dispatch(self):
        # A step that succeeded BEFORE outputs were captured
        # (legacy record): binding to it must fail closed.
        first = PlanStep(
            step_id="s1",
            intent="ابحث",
            tool="web_search",
            args={"query": "x"},
            state=StepState.SUCCEEDED,
            idempotency_key="p_test:s1",
            output_text=None,
        )
        plan = self._direct_plan(
            first, {"path": "o.txt",
                    "content": "{{steps.s1.output}}"}
        )
        dispatch = CapturingDispatch({
            "write_file": {"ok": True, "message": "كتب"},
        })
        outcome = self.make_run(dispatch).execute(plan)
        self.assertEqual(
            outcome.stopped_reason, "binding_unavailable"
        )
        self.assertEqual(dispatch.calls, [])
        bound = plan.steps[1]
        self.assertEqual(bound.state, StepState.BLOCKED)
        self.assertEqual(
            bound.blocked_reason,
            BlockedReason.BINDING_UNAVAILABLE,
        )
        self.assertEqual(len(self.notifier.escalated_calls), 1)

    def test_resume_resolves_from_stored_output(self):
        # The cross-process case: s1's output was captured and
        # persisted by an earlier run; this run only executes
        # s2, resolving purely from stored state.
        first = PlanStep(
            step_id="s1",
            intent="ابحث",
            tool="web_search",
            args={"query": "x"},
            state=StepState.SUCCEEDED,
            idempotency_key="p_test:s1",
            output_text="بيانات محفوظة",
        )
        plan = self._direct_plan(
            first, {"path": "o.txt",
                    "content": "وصل: {{steps.s1.output}}"}
        )
        dispatch = CapturingDispatch({
            "write_file": {"ok": True, "message": "كتب"},
        })
        outcome = self.make_run(dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        _, sent_args, _ = dispatch.calls_for("write_file")[0]
        self.assertEqual(sent_args["content"], "وصل: بيانات محفوظة")

    def test_too_large_output_blocks_without_dispatch(self):
        first = PlanStep(
            step_id="s1",
            intent="ابحث",
            tool="web_search",
            args={"query": "x"},
            state=StepState.SUCCEEDED,
            idempotency_key="p_test:s1",
            output_text="x" * (MAX_RESOLVED_ARG_CHARS + 1),
        )
        plan = self._direct_plan(
            first, {"path": "o.txt",
                    "content": "{{steps.s1.output}}"}
        )
        dispatch = CapturingDispatch({
            "write_file": {"ok": True, "message": "كتب"},
        })
        outcome = self.make_run(dispatch).execute(plan)
        self.assertEqual(
            outcome.stopped_reason, "binding_unavailable"
        )
        self.assertEqual(dispatch.calls, [])
        bound = plan.steps[1]
        self.assertEqual(bound.state, StepState.BLOCKED)
        self.assertEqual(
            bound.blocked_reason,
            BlockedReason.BINDING_UNAVAILABLE,
        )
        self.assertIn("تجاوزت", bound.error)

    def test_output_and_hash_survive_store_roundtrip(self):
        plan = self.create_plan(draft(
            step_draft("web_search", {"query": "منتجات"}),
            step_draft("write_file", {
                "path": "out.txt",
                "content": "القائمة: {{steps.s1.output}}",
            }),
        ))
        dispatch = CapturingDispatch({
            "web_search": {"ok": True, "message": SEARCH_TEXT},
            "write_file": {"ok": True, "message": "تمت الكتابة"},
        })
        self.make_run(dispatch).execute(plan)
        record = self.store.get(plan.plan_id)
        reloaded = record_to_plan(record, NOW)
        self.assertEqual(
            reloaded.steps[0].output_text, SEARCH_TEXT
        )
        self.assertEqual(
            reloaded.steps[1].resolved_args_hash,
            consent_digest_for(
                "write_file",
                {
                    "path": "out.txt",
                    "content": f"القائمة: {SEARCH_TEXT}",
                },
            ),
        )


class TestBindingAcceptanceShape(BindingHarness):
    def test_bound_write_verifies_against_materialized_content(
        self,
    ):
        # The 2026-11-06 incident, inverted, through the REAL
        # read-back verifier: search output flows into the
        # write, and the write's verification compares the file
        # against the MATERIALIZED content — not the token.
        plan = self.create_plan(draft(
            step_draft("web_search", {"query": "منتجات 11/11"}),
            step_draft("write_file", {
                "path": "products.txt",
                "content": "القائمة: {{steps.s1.output}}",
            }),
        ))
        materialized = f"القائمة: {SEARCH_TEXT}"
        dispatch = CapturingDispatch({
            "web_search": {"ok": True, "message": SEARCH_TEXT},
            "write_file": {"ok": True, "message": "تمت الكتابة"},
            "read_file": {"ok": True, "stdout": materialized},
        })
        verifier = ReadBackVerifier(
            dispatch=dispatch, tool_levels=dict(LEVELS)
        )
        outcome = self.make_run(
            dispatch, verifier=verifier
        ).execute(plan)
        self.assertIs(outcome.state, PlanState.DONE)
        second = plan.steps[1]
        self.assertEqual(second.state, StepState.SUCCEEDED)
        self.assertEqual(
            second.verify_outcome["verdict"], "verified"
        )
        self.assertEqual(self.notifier.escalated_calls, [])


class TestDecomposeRejectsBindings(BindingHarness):
    def test_decompose_draft_with_binding_is_not_applied(self):
        planner = FakePlanner(decompose_draft={
            "mode": "decompose",
            "steps": [
                step_draft("web_search", {"query": "x"}),
                step_draft("write_file", {
                    "path": "o.txt",
                    "content": "{{steps.s1.output}}",
                }),
            ],
        })
        create_planner = FakePlanner(draft(
            step_draft("write_file", {
                "path": "a.txt", "content": "x",
            }),
        ))
        plan = self.create_plan(
            draft(step_draft("write_file", {
                "path": "a.txt", "content": "x",
            })),
            planner=create_planner,
        )
        failed = plan.steps[0]
        failed.state = StepState.FAILED
        decompose = DecomposeStepUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=DESTRUCTIVE,
            clock=fixed_clock,
            notifier=self.notifier,
        )
        applied = decompose.execute(plan, failed)
        self.assertFalse(applied)
        self.assertEqual(len(plan.steps), 1)


if __name__ == "__main__":
    unittest.main()
