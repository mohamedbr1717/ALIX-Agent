"""Planner question-gate + fetch-budget fix (2026-10-31).

Incident: plan p_20261030T232235_fdf7 — a pure knowledge
question ("explain Qwen 3.8-27B FP8") endurance-escalated into
a plan, one web_fetch failed with HTTP 202, and the decomposer
burned the entire replan budget inventing fetch/extract
sub-steps until an EMPTY escalation reached the owner.

Three structural guarantees are pinned here:
1. A draft whose steps are ALL research reads (web_search /
   web_fetch) is declined at creation (research_not_plannable)
   so the agent answers in the plain loop. One non-research
   step makes it a genuine plan (owner's mixed-request rule).
2. A web_fetch failure is never decomposed and never touches
   the replan budget: one alternate-URL retry (from a succeeded
   search in the same plan), then a terminal fetch_failed
   escalation.
3. format_escalation carries the collected evidence (stored
   result summaries of succeeded steps), never a bare failure.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.entities import Plan, PlanStep
from domain.planning.states import PlanState, StepState

from features.planning.application.dto.planning import (
    CreatePlanRequest,
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
    RunPlanUseCase,
)
from features.planning.infrastructure.adapters.contract_ok_verifier import (
    ContractOkVerifier,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)
from features.planning.interfaces import formatting

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)

ALLOWLIST = frozenset(
    {"web_search", "web_fetch", "read_file", "write_file"}
)
SCHEMAS = {
    "web_search": frozenset({"query"}),
    "web_fetch": frozenset({"url"}),
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
}

URL_A = "https://a.example/spec"
URL_B = "https://b.example/spec"


def fixed_clock():
    return NOW


def draft_step(tool, intent="خطوة", args=None):
    return {"intent": intent, "tool": tool, "args": args or {}}


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


class FakeDispatch(ToolDispatchPort):
    def __init__(self, results=None):
        self._results = results or {}
        self.calls = []

    def execute(self, tool, args):
        self.calls.append((tool, dict(args)))
        queue = self._results.get(tool)
        if queue:
            return queue.pop(0)
        return {"ok": True, "message": f"تم {tool}"}


class RecordingNotifier:
    def __init__(self):
        self.created_calls = []
        self.escalated_calls = []
        self.finished_calls = []

    def created(self, plan, approval_steps):
        self.created_calls.append(plan.plan_id)

    def decomposed(self, plan, failed_step, new_step_ids):
        pass

    def escalated(self, plan, failed_step, reason):
        self.escalated_calls.append((plan.plan_id, reason))

    def finished(self, plan):
        self.finished_calls.append(plan.plan_id)

    def recovered(self, plans):
        pass


class FetchGateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(Path(self._tmp.name) / "plans.json")
        self.notifier = RecordingNotifier()

    def create_outcome(self, planner):
        use_case = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
        )
        return use_case.execute(
            CreatePlanRequest(goal="هدف", origin="interactive")
        )

    def build_run(self, planner, dispatch):
        decompose = DecomposeStepUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
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
        )


class TestQuestionGate(FetchGateCase):
    def test_all_research_draft_is_declined(self):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step("web_search", "بحث", {"query": "q"}),
                    draft_step("web_fetch", "جلب", {"url": URL_A}),
                ]
            }
        )
        outcome = self.create_outcome(planner)
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.reason, "research_not_plannable")
        self.assertIsNone(outcome.plan)

    def test_fetch_only_draft_is_declined(self):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step("web_fetch", "جلب ١", {"url": URL_A}),
                    draft_step("web_fetch", "جلب ٢", {"url": URL_B}),
                ]
            }
        )
        outcome = self.create_outcome(planner)
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.reason, "research_not_plannable")

    def test_one_effect_step_makes_it_a_plan(self):
        # Owner's mixed-request ruling: a single non-research
        # step (here a write) makes the draft a genuine plan.
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step("web_search", "بحث", {"query": "q"}),
                    draft_step("web_fetch", "جلب", {"url": URL_A}),
                    draft_step(
                        "write_file",
                        "حفظ",
                        {"path": "x", "content": "y"},
                    ),
                ]
            }
        )
        outcome = self.create_outcome(planner)
        self.assertTrue(outcome.created, outcome)
        self.assertEqual(len(outcome.plan.steps), 3)


class TestFetchBudget(FetchGateCase):
    def _research_plan(self, planner):
        outcome = self.create_outcome(planner)
        assert outcome.created, outcome
        return outcome.plan

    def test_fetch_failure_retries_alternate_url_once(self):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step("web_search", "بحث", {"query": "q"}),
                    draft_step("web_fetch", "جلب", {"url": URL_A}),
                    draft_step(
                        "write_file",
                        "حفظ",
                        {"path": "x", "content": "y"},
                    ),
                ]
            }
        )
        plan = self._research_plan(planner)
        dispatch = FakeDispatch(
            results={
                "web_search": [
                    {
                        "ok": True,
                        "message": (
                            f"النتيجة الأولى {URL_A} "
                            f"وبديلها {URL_B} كامل"
                        ),
                    }
                ],
                "web_fetch": [
                    {"ok": False, "error": "HTTP 202"},
                    {"ok": True, "message": "المحتوى الكامل"},
                ],
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)

        self.assertIs(outcome.state, PlanState.DONE)
        fetch_urls = [
            args["url"]
            for tool, args in dispatch.calls
            if tool == "web_fetch"
        ]
        self.assertEqual(fetch_urls, [URL_A, URL_B])
        # The decomposer was never consulted, budget untouched.
        self.assertEqual(planner.decompose_calls, 0)
        self.assertEqual(plan.replans_used, 0)

    def test_fetch_failure_without_alternate_escalates_terminally(self):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step("web_search", "بحث", {"query": "q"}),
                    draft_step("web_fetch", "جلب", {"url": URL_A}),
                    draft_step(
                        "write_file",
                        "حفظ",
                        {"path": "x", "content": "y"},
                    ),
                ]
            }
        )
        plan = self._research_plan(planner)
        dispatch = FakeDispatch(
            results={
                "web_search": [
                    {"ok": True, "message": "نتائج بلا روابط مباشرة"}
                ],
                "web_fetch": [{"ok": False, "error": "HTTP 202"}],
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)

        fetch_step = plan.steps[1]
        self.assertIs(fetch_step.state, StepState.FAILED)
        self.assertEqual(outcome.stopped_reason, "fetch_failed")
        self.assertTrue(plan.escalated)
        self.assertEqual(len(self.notifier.escalated_calls), 1)
        self.assertEqual(planner.decompose_calls, 0)
        self.assertEqual(plan.replans_used, 0)
        # The remaining step was NOT executed.
        self.assertIs(plan.steps[2].state, StepState.PENDING)
        self.assertEqual(
            [tool for tool, _ in dispatch.calls],
            ["web_search", "web_fetch"],
        )

    def test_non_fetch_failure_still_decomposes(self):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step("read_file", "قراءة", {"path": "x"}),
                    draft_step(
                        "write_file",
                        "حفظ",
                        {"path": "x", "content": "y"},
                    ),
                ]
            },
            decompose_script=[{"mode": "give_up"}],
        )
        plan = self._research_plan(planner)
        dispatch = FakeDispatch(
            results={"read_file": [{"ok": False, "error": "boom"}]}
        )
        self.build_run(planner, dispatch).execute(plan)
        # Regression guard: ordinary failures keep the ADaPT path.
        self.assertEqual(planner.decompose_calls, 1)
        self.assertEqual(plan.replans_used, 1)


class TestEscalationEvidence(unittest.TestCase):
    def _plan(self, steps):
        return Plan(
            plan_id="p_test",
            goal="اشرح النموذج",
            origin="interactive",
            steps=steps,
            expires_at="2026-11-01T00:00:00+00:00",
        )

    def test_escalation_carries_collected_evidence(self):
        search = PlanStep(
            step_id="s1",
            intent="بحث عن خصائص النموذج",
            tool="web_search",
            state=StepState.SUCCEEDED,
            idempotency_key="p_test:s1",
            result_ref="مقتطف: 27.8B معامل ويحتاج 30.9GB للتنزيل",
        )
        fetch = PlanStep(
            step_id="s2",
            intent="جلب صفحة النموذج",
            tool="web_fetch",
            state=StepState.FAILED,
            idempotency_key="p_test:s2",
            error="HTTP 202",
        )
        text = formatting.format_escalation(
            self._plan([search, fetch]), fetch, "فشل الجلب", NOW
        )
        self.assertIn("ما جُمع:", text)
        self.assertIn("30.9GB", text)
        self.assertIn("بحث عن خصائص النموذج", text)

    def test_no_evidence_section_without_results(self):
        search = PlanStep(
            step_id="s1",
            intent="بحث",
            tool="web_search",
            state=StepState.SUCCEEDED,
            idempotency_key="p_test:s1",
        )
        fetch = PlanStep(
            step_id="s2",
            intent="جلب",
            tool="web_fetch",
            state=StepState.FAILED,
            idempotency_key="p_test:s2",
            error="HTTP 202",
        )
        text = formatting.format_escalation(
            self._plan([search, fetch]), fetch, "فشل الجلب", NOW
        )
        self.assertNotIn("ما جُمع:", text)


if __name__ == "__main__":
    unittest.main()
