"""Decision 1 — the deterministic executor + budget (spec §4.3/§4.5).

No LLM inside the loop (dispatch happens only through the port,
planner calls are counted), strict step order, the code-enforced
replan budget (2) and depth cap (2), ADaPT decomposition with
total-step cap, and the safe fallback when creation is rejected.
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
from features.planning.application.mapping import plan_to_record
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.ports.verifier import (
    VerifierPort,
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
from features.planning.composition import (
    build_planning_controller,
)
from features.planning.infrastructure.adapters.contract_ok_verifier import (
    ContractOkVerifier,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat(timespec="seconds")

ALLOWLIST = frozenset({"read_file", "list_files", "write_file"})
SCHEMAS = {
    "read_file": frozenset({"path"}),
    "list_files": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
}


def fixed_clock():
    return NOW


def draft_step(tool="read_file", intent="خطوة", args=None):
    return {
        "intent": intent,
        "tool": tool,
        "args": args if args is not None else {"path": "x"},
    }


class FakePlanner(PlannerPort):
    """Scripted planner with call counters (the LLM seam)."""

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
    """Scripted dispatch: per-tool result queues + a call log."""

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


class ExecutorCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.notifier = RecordingNotifier()

    def build_run(self, planner, dispatch, verifier=None):
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
            verifier=verifier or ContractOkVerifier(),
            store=self.store,
            decompose=decompose,
            clock=fixed_clock,
            notifier=self.notifier,
        )

    def create(self, planner, steps):
        use_case = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
        )
        outcome = use_case.execute(
            CreatePlanRequest(
                goal="هدف",
                origin="interactive",
            )
        )
        assert outcome.created, outcome
        return outcome.plan


class TestDeterminismAndOrder(ExecutorCase):
    def test_no_llm_inside_the_loop_and_strict_order(self):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step("list_files", "أولى", {}),
                    draft_step("read_file", "ثانية"),
                    draft_step("write_file", "ثالثة",
                               {"path": "y", "content": "z"}),
                ]
            }
        )
        plan = self.create(planner, None)
        dispatch = FakeDispatch()
        outcome = self.build_run(planner, dispatch).execute(plan)

        self.assertIs(outcome.state, PlanState.DONE)
        self.assertEqual(
            [tool for tool, _ in dispatch.calls],
            ["list_files", "read_file", "write_file"],
        )
        # Planner was used ONCE (creation), never between steps.
        self.assertEqual(planner.plan_calls, 1)
        self.assertEqual(planner.decompose_calls, 0)
        self.assertEqual(
            self.notifier.finished_calls, [plan.plan_id]
        )
        # Every step persisted as succeeded with a result summary.
        record = self.store.get(plan.plan_id)
        self.assertEqual(
            [s.state for s in record.steps],
            ["succeeded"] * 3,
        )
        self.assertTrue(
            all(s.result_ref for s in record.steps)
        )

    def test_blocked_first_step_stops_dispatch(self):
        planner = FakePlanner(
            plan_draft={"steps": [draft_step(), draft_step()]}
        )
        plan = self.create(planner, None)
        # Owner cancels the first step before the run (SKIPPED is
        # passable); instead block it: simulate approval denial
        # on step 1 — nothing else may be dispatched.
        dispatch = FakeDispatch(
            results={
                "read_file": [
                    {
                        "ok": False,
                        "error": "رفض المستخدم تنفيذ العملية. "
                        "أُلغيت هذه العملية نهائيًا.",
                    }
                ]
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)
        self.assertEqual(len(dispatch.calls), 1)
        self.assertIs(outcome.state, PlanState.BLOCKED)


class TestReplanBudget(ExecutorCase):
    def test_budget_two_then_escalate_without_a_third_call(self):
        planner = FakePlanner(
            plan_draft={"steps": [draft_step()]},
            decompose_script=[
                {"mode": "decompose", "steps": [draft_step()]},
                {"mode": "decompose", "steps": [draft_step()]},
                {"mode": "decompose", "steps": [draft_step()]},
            ],
        )
        plan = self.create(planner, None)
        dispatch = FakeDispatch(
            results={
                "read_file": [
                    {"ok": False, "error": "boom"}
                ]
                * 10
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)

        # Two decompositions consumed the budget; the third
        # failure escalated WITHOUT another planner call.
        self.assertEqual(planner.decompose_calls, 2)
        self.assertIs(outcome.state, PlanState.ESCALATED)
        self.assertEqual(plan.replans_used, 2)
        self.assertEqual(len(self.notifier.escalated_calls), 1)
        record = self.store.get(plan.plan_id)
        self.assertEqual(record.replans_used, 2)
        self.assertTrue(record.escalated)

    def test_depth_cap_escalates_without_calling_planner(self):
        planner = FakePlanner()
        plan = Plan(
            plan_id="p_manual",
            goal="هدف",
            origin="interactive",
            steps=[
                PlanStep(
                    step_id="s1.1.1",
                    intent="عميقة",
                    tool="read_file",
                    args={"path": "x"},
                    depth=2,
                    parent_step_id="s1.1",
                    idempotency_key="p_manual:s1.1.1",
                    created_at=NOW_ISO,
                    updated_at=NOW_ISO,
                )
            ],
            created_at=NOW_ISO,
            updated_at=NOW_ISO,
            expires_at="2026-10-28T12:00:00+00:00",
        )
        self.store.save(plan_to_record(plan, NOW))
        dispatch = FakeDispatch(
            results={
                "read_file": [{"ok": False, "error": "boom"}]
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)
        self.assertEqual(planner.decompose_calls, 0)
        self.assertIs(outcome.state, PlanState.ESCALATED)

    def test_give_up_escalates_and_notifies_once(self):
        planner = FakePlanner(
            plan_draft={"steps": [draft_step()]},
            decompose_script=[{"mode": "give_up"}],
        )
        plan = self.create(planner, None)
        dispatch = FakeDispatch(
            results={
                "read_file": [{"ok": False, "error": "boom"}]
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)
        self.assertIs(outcome.state, PlanState.ESCALATED)
        self.assertEqual(planner.decompose_calls, 1)
        self.assertEqual(len(self.notifier.escalated_calls), 1)
        # No double notification: escalation replaces "finished".
        self.assertEqual(self.notifier.finished_calls, [])


class TestDecomposition(ExecutorCase):
    def test_successful_decomposition_recovers_the_plan(self):
        planner = FakePlanner(
            plan_draft={"steps": [draft_step()]},
            decompose_script=[
                {
                    "mode": "decompose",
                    "steps": [
                        draft_step("list_files", "فرعية أ", {}),
                        draft_step("list_files", "فرعية ب", {}),
                    ],
                }
            ],
        )
        plan = self.create(planner, None)
        dispatch = FakeDispatch(
            results={
                "read_file": [{"ok": False, "error": "boom"}]
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)

        self.assertIs(outcome.state, PlanState.DONE)
        failed = plan.step("s1")
        self.assertIs(failed.state, StepState.FAILED)
        self.assertTrue(failed.resolved_by_decomposition)
        self.assertEqual(
            [s.step_id for s in plan.steps],
            ["s1", "s1.1", "s1.2"],
        )
        self.assertTrue(
            all(
                s.state is StepState.SUCCEEDED
                for s in plan.steps[1:]
            )
        )
        self.assertEqual(
            self.notifier.decomposed_calls,
            [("s1", ["s1.1", "s1.2"])],
        )
        self.assertEqual(plan.replans_used, 1)

    def test_rewrite_tail_supersedes_pending_steps(self):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step(),
                    draft_step("list_files", "ذيل قديم", {}),
                ]
            },
            decompose_script=[
                {
                    "mode": "rewrite_tail",
                    "steps": [
                        draft_step("list_files", "ذيل جديد", {})
                    ],
                }
            ],
        )
        plan = self.create(planner, None)
        dispatch = FakeDispatch(
            results={
                "read_file": [{"ok": False, "error": "boom"}]
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)

        self.assertIs(outcome.state, PlanState.DONE)
        states = {s.step_id: s.state for s in plan.steps}
        self.assertIs(states["s1"], StepState.FAILED)
        self.assertIs(states["s2"], StepState.SKIPPED)
        self.assertIs(states["s3"], StepState.SUCCEEDED)

    def test_total_steps_cap_blocks_oversized_decomposition(self):
        planner = FakePlanner(
            decompose_script=[
                {
                    "mode": "decompose",
                    "steps": [draft_step() for _ in range(4)],
                }
            ]
        )
        steps = []
        for index in range(1, 19):
            step_id = f"s{index}"
            steps.append(
                PlanStep(
                    step_id=step_id,
                    intent=f"خطوة {index}",
                    tool="read_file",
                    args={"path": "x"},
                    state=(
                        StepState.SUCCEEDED
                        if index < 18
                        else StepState.PENDING
                    ),
                    idempotency_key=f"p_big:{step_id}",
                    created_at=NOW_ISO,
                    updated_at=NOW_ISO,
                )
            )
        plan = Plan(
            plan_id="p_big",
            goal="هدف",
            origin="interactive",
            steps=steps,
            created_at=NOW_ISO,
            updated_at=NOW_ISO,
            expires_at="2026-10-28T12:00:00+00:00",
        )
        self.store.save(plan_to_record(plan, NOW))
        dispatch = FakeDispatch(
            results={
                "read_file": [{"ok": False, "error": "boom"}]
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)

        # 18 + 4 = 22 > MAX_TOTAL_STEPS (20): rejected whole,
        # plan escalates with the original 18 steps untouched.
        self.assertIs(outcome.state, PlanState.ESCALATED)
        self.assertEqual(len(plan.steps), 18)

    def test_decomposition_with_unknown_tool_rejected_whole(self):
        planner = FakePlanner(
            plan_draft={"steps": [draft_step()]},
            decompose_script=[
                {
                    "mode": "decompose",
                    "steps": [
                        draft_step("list_files", "سليمة", {}),
                        draft_step("delete_everything", "خبيثة"),
                    ],
                }
            ],
        )
        plan = self.create(planner, None)
        dispatch = FakeDispatch(
            results={
                "read_file": [{"ok": False, "error": "boom"}]
            }
        )
        outcome = self.build_run(planner, dispatch).execute(plan)
        # No silent dropping of the bad step: nothing decomposed.
        self.assertIs(outcome.state, PlanState.ESCALATED)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(
            [tool for tool, _ in dispatch.calls], ["read_file"]
        )


class TestVerifierSeam(ExecutorCase):
    def test_vetoing_verifier_fails_the_step(self):
        class VetoVerifier(VerifierPort):
            def verify(self, step, result):
                return False

        planner = FakePlanner(
            plan_draft={"steps": [draft_step()]},
            decompose_script=[{"mode": "give_up"}],
        )
        plan = self.create(planner, None)
        dispatch = FakeDispatch()  # tool says ok
        outcome = self.build_run(
            planner, dispatch, verifier=VetoVerifier()
        ).execute(plan)
        self.assertIs(plan.step("s1").state, StepState.FAILED)
        self.assertIs(outcome.state, PlanState.ESCALATED)


class TestSafeFallback(ExecutorCase):
    def test_creation_rejection_means_no_plan_and_no_dispatch(
        self,
    ):
        class BadLLM:
            def chat(self, messages, tools=None):
                return {
                    "content": '{"steps": [{"intent": "x", '
                    '"tool": "delete_everything", "args": {}}]}'
                }

        dispatched = []

        def spy_execute(tool, args):
            dispatched.append(tool)
            return {"ok": True, "message": "تم"}

        controller = build_planning_controller(
            llm=BadLLM(),
            execute_tool=spy_execute,
            base_dir=Path(self._tmp.name),
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
        )
        outcome = controller.try_create_and_run(
            "هدف", "interactive", prior_actions=[]
        )
        self.assertFalse(outcome.handled)
        self.assertEqual(outcome.reason, "tool_not_in_allowlist")
        self.assertEqual(dispatched, [])
        self.assertEqual(
            controller.handle_status({})["plans"], []
        )


if __name__ == "__main__":
    unittest.main()
