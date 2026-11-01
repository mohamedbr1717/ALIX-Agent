"""Decision 6 — ask or act (2026-11-01).

Owner's rulings pinned here:
- The planner may reply {"clarify": question} instead of a
  draft: no plan is created, the question is the outcome,
  and the controller treats it as HANDLED (falling back to
  direct execution would invent the missing values).
- Scheduled origin + an unverifiable write step => ask
  BEFORE execution (no plan). Interactive origin executes
  without asking; the same facts are disclosed on the
  plan's creation notice instead.
- The rule reads facts only: Policy levels + the read-back
  verifier's default-spec coverage. Destructive steps are
  out (born blocked / approval cards already ask).
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.ask import unverifiable_write_steps
from domain.planning.entities import PlanStep
from domain.planning.states import StepState
from domain.planning.validation import ValidatedStep

from features.planning.application.dto.planning import (
    CreatePlanRequest,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.use_cases.create_plan import (
    CreatePlanUseCase,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)
from features.planning.infrastructure.adapters.llm_planner import (
    _PLAN_SYSTEM,
)
from features.planning.infrastructure.adapters.readback_verifier import (
    ReadBackVerifier,
)
from features.planning.interfaces.controllers.planning_controller import (
    PlanningController,
)
from features.planning.interfaces.notifier import PlanNotifier

NOW = datetime(2026, 11, 1, 17, 30, tzinfo=timezone.utc)

ALLOWLIST = frozenset(
    {"web_search", "read_file", "write_file", "calendar_add",
     "delete_file", "schedule_task"}
)
SCHEMAS = {
    "web_search": frozenset({"query"}),
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
    "calendar_add": frozenset({"title", "start"}),
    "delete_file": frozenset({"path"}),
    "schedule_task": frozenset({"task"}),
}
LEVELS = {
    "web_search": "read",
    "read_file": "read",
    "write_file": "write",
    "calendar_add": "execute",
    "delete_file": "destructive",
    "schedule_task": "write",
}
VERIFIABLE = ReadBackVerifier.default_spec_tools()


def fixed_clock():
    return NOW


def draft_step(tool, intent="خطوة", args=None, **kw):
    step = {"intent": intent, "tool": tool, "args": args or {}}
    step.update(kw)
    return step


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
        self.notices = []
        self.created_calls = 0

    def created(self, plan, approval_steps):
        self.created_calls += 1

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
        self.notices.append(list(notices))


class CreateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.notifier = SpyNotifier()

    def create(self, planner, origin="interactive", **kw):
        use_case = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset({"delete_file"}),
            confirming_tools=frozenset(),
            clock=fixed_clock,
            notifier=self.notifier,
            tool_levels=dict(LEVELS),
            verifiable_tools=VERIFIABLE,
            **kw,
        )
        return use_case.execute(
            CreatePlanRequest(goal="هدف", origin=origin)
        )


class TestRule(unittest.TestCase):
    def _step(self, tool, verify=None):
        return ValidatedStep(
            intent="قصد", tool=tool, args={}, verify=verify
        )

    def test_hits_and_exemptions(self):
        steps = [
            self._step("write_file"),          # verifiable now
            self._step("calendar_add"),        # verifiable
            self._step("read_file"),           # read level
            self._step("delete_file"),         # destructive
            self._step(
                "write_file", verify={"channel": "x"}
            ),                                  # own spec
            self._step("schedule_task"),       # hit
        ]
        hits = unverifiable_write_steps(
            steps,
            tool_levels=dict(LEVELS),
            verifiable_tools=VERIFIABLE,
        )
        # write_file left the hit set on 2026-11-01: it gained
        # a default read-back spec (content match), so only
        # the still-unverifiable write remains a hit.
        self.assertEqual([s.tool for s in hits], ["schedule_task"])

    def test_default_spec_tools_match_verifier_behavior(self):
        # The index must not drift from _spec_for's truth.
        verifier = ReadBackVerifier(
            dispatch=None, tool_levels=dict(LEVELS)
        )

        def spec(tool, args):
            step = PlanStep(
                step_id="s", intent="x", tool=tool, args=args,
                state=StepState.PENDING,
                idempotency_key="p:s",
            )
            return verifier._spec_for(step, {})

        for tool in ("calendar_add", "calendar_delete",
                     "remember_fact", "write_file"):
            self.assertIn(tool, VERIFIABLE)
        self.assertIsNotNone(
            spec("calendar_add",
                 {"title": "t", "start": "2026-11-02T10:00:00"})
        )
        self.assertIsNotNone(spec("calendar_delete", {}))
        self.assertIsNotNone(spec("remember_fact", {"fact": "x"}))
        # write_file (2026-11-01): spec exists only with a
        # path AND a content within the read-back cap.
        self.assertIsNotNone(
            spec("write_file", {"path": "x", "content": "y"})
        )
        self.assertIsNone(spec("write_file", {"path": "x"}))
        self.assertIsNone(
            spec(
                "write_file",
                {"path": "x", "content": "y" * 4001},
            )
        )


class TestClarifyChannel(CreateCase):
    def test_planner_question_creates_no_plan(self):
        planner = FakePlanner(
            {"clarify": "ما اسم الملف المطلوب حفظ الملخص فيه؟"}
        )
        outcome = self.create(planner)
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.reason, "clarification_needed")
        self.assertIn("اسم الملف", outcome.detail)
        self.assertEqual(len(self.store.list_all()), 0)
        self.assertEqual(len(self.notifier.clarifications), 1)

    def test_malformed_clarify_is_rejected_as_draft(self):
        planner = FakePlanner({"clarify": "   "})
        outcome = self.create(planner)
        self.assertFalse(outcome.created)
        self.assertNotEqual(outcome.reason, "clarification_needed")
        self.assertEqual(len(self.notifier.clarifications), 0)

    def test_prompt_contract_mentions_clarify(self):
        self.assertIn('"clarify"', _PLAN_SYSTEM)


class TestAskRule(CreateCase):
    # schedule_task is the unverifiable write here: write_file
    # gained a read-back spec on 2026-11-01 and no longer asks
    # (its verifiable path is test_scheduled_verifiable_write_proceeds'
    # sibling in test_planning_writeback.py).
    WRITE_DRAFT = {"steps": [
        draft_step("read_file", "قراءة", {"path": "x"}),
        draft_step("schedule_task", "جدولة",
                   {"task": "حفظ التقرير غدًا"}),
    ]}

    def test_scheduled_unverifiable_write_asks(self):
        outcome = self.create(
            FakePlanner(self.WRITE_DRAFT), origin="scheduled"
        )
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.reason, "clarification_needed")
        self.assertIn("schedule_task", outcome.detail)
        self.assertEqual(len(self.store.list_all()), 0)
        self.assertEqual(len(self.notifier.clarifications), 1)

    def test_interactive_executes_with_disclosure(self):
        outcome = self.create(
            FakePlanner(self.WRITE_DRAFT), origin="interactive"
        )
        self.assertTrue(outcome.created, outcome)
        self.assertEqual(len(self.notifier.clarifications), 0)
        self.assertEqual(len(self.notifier.notices), 1)
        self.assertIn("schedule_task", self.notifier.notices[0][0])
        self.assertEqual(self.notifier.created_calls, 1)

    def test_scheduled_verifiable_write_proceeds(self):
        draft = {"steps": [
            draft_step("read_file", "قراءة", {"path": "x"}),
            draft_step("calendar_add", "إضافة",
                       {"title": "t", "start": "s"}),
        ]}
        outcome = self.create(FakePlanner(draft), origin="scheduled")
        self.assertTrue(outcome.created, outcome)
        self.assertEqual(len(self.notifier.clarifications), 0)

    def test_scheduled_destructive_is_born_blocked_not_asked(self):
        draft = {"steps": [
            draft_step("read_file", "قراءة", {"path": "x"}),
            draft_step("delete_file", "حذف", {"path": "x"}),
        ]}
        outcome = self.create(FakePlanner(draft), origin="scheduled")
        self.assertTrue(outcome.created, outcome)
        step = outcome.plan.steps[1]
        self.assertEqual(step.state.value, "blocked")
        self.assertEqual(
            step.blocked_reason.value, "scheduled_policy"
        )
        self.assertEqual(len(self.notifier.clarifications), 0)


class TestControllerHandling(CreateCase):
    def test_clarification_is_handled_with_the_question(self):
        create = CreatePlanUseCase(
            planner=FakePlanner({"clarify": "أي حساب بريد؟"}),
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
            notifier=self.notifier,
        )
        from features.planning.application.use_cases.cancel_plan import (
            CancelPlanUseCase,
        )
        from features.planning.application.use_cases.get_plan import (
            GetPlanUseCase,
        )
        from features.planning.application.use_cases.list_plans import (
            ListPlansUseCase,
        )
        from features.planning.application.use_cases.recover_plans import (
            RecoverPlansUseCase,
        )
        from features.planning.application.use_cases.release_step import (
            ReleaseStepUseCase,
        )
        from features.planning.application.use_cases.decompose_step import (
            DecomposeStepUseCase,
        )
        from features.planning.application.use_cases.run_plan import (
            RunPlanUseCase,
        )
        from features.planning.application.ports.tool_dispatch import (
            ToolDispatchPort,
        )
        from features.planning.infrastructure.adapters.contract_ok_verifier import (
            ContractOkVerifier,
        )

        class _Dispatch(ToolDispatchPort):
            def execute(self, tool, args):
                return {"ok": True, "message": "تم"}

        planner = FakePlanner({"clarify": "أي حساب بريد؟"})
        notifier = PlanNotifier(sender=None, clock=fixed_clock)
        run = RunPlanUseCase(
            dispatch=_Dispatch(),
            verifier=ContractOkVerifier(),
            store=self.store,
            decompose=DecomposeStepUseCase(
                planner=planner,
                store=self.store,
                allowlist=ALLOWLIST,
                tool_schemas=SCHEMAS,
                destructive_tools=frozenset(),
                clock=fixed_clock,
                notifier=notifier,
            ),
            clock=fixed_clock,
            notifier=notifier,
        )
        controller = PlanningController(
            get_plan=GetPlanUseCase(
                store=self.store, clock=fixed_clock
            ),
            list_plans=ListPlansUseCase(
                store=self.store, clock=fixed_clock
            ),
            cancel_plan=CancelPlanUseCase(
                store=self.store, clock=fixed_clock
            ),
            release_step=ReleaseStepUseCase(
                store=self.store, clock=fixed_clock
            ),
            recover_plans=RecoverPlansUseCase(
                store=self.store, clock=fixed_clock,
                notifier=notifier,
            ),
            create_plan=create,
            run_plan=run,
            notifier=notifier,
            clock=fixed_clock,
        )
        outcome = controller.try_create_and_run(
            "هدف", "interactive"
        )
        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.state, "clarification_needed")
        self.assertIn("أي حساب بريد؟", outcome.reply_text)


class TestNotifierTexts(unittest.TestCase):
    def test_clarification_and_notices_render(self):
        notifier = PlanNotifier(sender=None, clock=fixed_clock)
        notifier.clarification("هدف", "سؤال؟")
        notifier.plan_notices(None, ["⚠️ سطر"])
        texts = notifier.drain()
        self.assertEqual(len(texts), 2)
        self.assertIn("❓", texts[0])
        self.assertIn("سؤال؟", texts[0])
        self.assertIn("⚠️ سطر", texts[1])


if __name__ == "__main__":
    unittest.main()
