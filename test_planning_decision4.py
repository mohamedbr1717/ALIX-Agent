"""Decision 4 — means selection + outcome log (2026-11-01).

Owner's rulings pinned here:
- Level: derived log + planner advisory + a small DECLARED
  rules table. No semantic intent gate (an LLM judging an LLM
  is not a gate; keyword rules are brittle — spec addendum).
- Declared context bans are mechanical and enforced at
  acceptance (notify on a server without Termux:API).
- The log records history truthfully: a vacuously successful
  binding counts as the success it was; Policy/approval
  denials count as denials, never as means failures.
- The log is DERIVED from stored plans, keyed by (family,
  tool) from the domain table; unknown tools are "other".
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.entities import Plan, PlanStep
from domain.planning.means import (
    aggregate_outcomes,
    best_tool_per_family,
    family_of,
)
from domain.planning.states import BlockedReason, StepState

from features.planning.application.dto.planning import (
    CreatePlanRequest,
    PlanRecord,
    PlanStepRecord,
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
from features.planning.application.use_cases.means_log import (
    MeansLogUseCase,
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
from features.planning.infrastructure.adapters.llm_planner import (
    LLMPlannerAdapter,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-11-01T12:00:00+00:00"

ALLOWLIST = frozenset(
    {"web_search", "web_fetch", "notify", "calendar_add",
     "read_file", "write_file"}
)
SCHEMAS = {
    "web_search": frozenset({"query"}),
    "web_fetch": frozenset({"url"}),
    "notify": frozenset({"message"}),
    "calendar_add": frozenset({"title", "start"}),
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
}


def fixed_clock():
    return NOW


def draft_step(tool, intent="خطوة", args=None):
    return {"intent": intent, "tool": tool, "args": args or {}}


class FakePlanner(PlannerPort):
    def __init__(self, plan_draft=None):
        self._plan_draft = plan_draft or {"steps": []}
        self.contexts = []

    def plan(self, goal, prior_actions, context):
        self.contexts.append(context)
        return self._plan_draft

    def decompose(self, goal, failed_step, remaining_steps):
        return {"mode": "give_up"}


class FakeDispatch(ToolDispatchPort):
    def execute(self, tool, args):
        return {"ok": True, "message": f"تم {tool}"}


class RecordingNotifier:
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


def make_step(step_id, tool, state, **kw):
    return PlanStep(
        step_id=step_id,
        intent="قصد",
        tool=tool,
        state=state,
        idempotency_key=f"p_agg:{step_id}",
        **kw,
    )


def make_plan(steps):
    return Plan(
        plan_id="p_agg",
        goal="هدف",
        origin="interactive",
        steps=steps,
        expires_at="2027-01-01T00:00:00+00:00",
    )


class TestFamilies(unittest.TestCase):
    def test_known_tools_and_other(self):
        self.assertEqual(family_of("calendar_add"), "calendar")
        self.assertEqual(family_of("gmail_send"), "mail")
        self.assertEqual(family_of("web_search"), "web")
        self.assertEqual(family_of("resolve_contact"), "contacts")
        self.assertEqual(family_of("notify"), "notify")
        self.assertEqual(family_of("remember_fact"), "memory")
        self.assertEqual(family_of("tool_from_the_future"), "other")


class TestAggregation(unittest.TestCase):
    def test_counts_are_truthful_per_family_and_tool(self):
        plan = make_plan([
            make_step(
                "s1", "calendar_add", StepState.SUCCEEDED,
                verify_outcome={"verdict": "verified"},
            ),
            # Vacuous success (exempt read): recorded AS the
            # success it was — the log does not editorialize.
            make_step(
                "s2", "web_search", StepState.SUCCEEDED,
                verify_outcome={
                    "verdict": "verified", "channel": "exempt",
                },
            ),
            make_step("s3", "calendar_add", StepState.FAILED),
            # A denial is not a means failure.
            make_step(
                "s4", "notify", StepState.BLOCKED,
                blocked_reason=BlockedReason.APPROVAL_DENIED,
            ),
            make_step(
                "s5", "remember_fact", StepState.BLOCKED,
                blocked_reason=(
                    BlockedReason.VERIFICATION_UNKNOWN
                ),
                outcome_unknown=True,
                verify_outcome={"verdict": "unknown"},
            ),
        ])
        stats = aggregate_outcomes([plan])

        cal = stats[("calendar", "calendar_add")]
        self.assertEqual(
            (cal["steps"], cal["succeeded"], cal["verified"],
             cal["failed"]),
            (2, 1, 1, 1),
        )
        web = stats[("web", "web_search")]
        self.assertEqual((web["succeeded"], web["verified"]), (1, 1))
        note = stats[("notify", "notify")]
        self.assertEqual(
            (note["blocked"], note["denied"], note["failed"]),
            (1, 1, 0),
        )
        mem = stats[("memory", "remember_fact")]
        self.assertEqual(
            (mem["blocked"], mem["outcome_unknown"],
             mem["unknown_verdicts"]),
            (1, 1, 1),
        )

        best = best_tool_per_family(stats)
        self.assertEqual(best["calendar"], "calendar_add")
        self.assertEqual(best["web"], "web_search")
        self.assertNotIn("memory", best)
        self.assertNotIn("notify", best)


class CreateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )

    def create(self, planner, **kw):
        use_case = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
            **kw,
        )
        return use_case.execute(
            CreatePlanRequest(goal="هدف", origin="interactive")
        )


class TestDeclaredBans(CreateCase):
    DRAFT = {
        "steps": [
            draft_step("web_search", "بحث", {"query": "q"}),
            draft_step("notify", "إشعار", {"message": "m"}),
        ]
    }

    def test_notify_banned_on_server(self):
        outcome = self.create(
            FakePlanner(self.DRAFT),
            runtime_tags=frozenset({"server"}),
        )
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.reason, "means_rule_banned")
        self.assertIn("notify", outcome.detail)

    def test_notify_allowed_on_termux(self):
        outcome = self.create(
            FakePlanner(self.DRAFT),
            runtime_tags=frozenset({"termux"}),
        )
        self.assertTrue(outcome.created, outcome)

    def test_no_tags_no_bans(self):
        outcome = self.create(FakePlanner(self.DRAFT))
        self.assertTrue(outcome.created, outcome)


class TestAdvisoryContext(CreateCase):
    DRAFT = {
        "steps": [
            draft_step("read_file", "قراءة", {"path": "x"}),
            draft_step(
                "write_file", "حفظ",
                {"path": "x", "content": "y"},
            ),
        ]
    }

    def test_hints_and_preferences_reach_the_planner(self):
        planner = FakePlanner(self.DRAFT)
        outcome = self.create(
            planner,
            means_hints_provider=lambda: ["سطر من السجلّ"],
        )
        self.assertTrue(outcome.created, outcome)
        hints = planner.contexts[0].get("means_hints", [])
        self.assertIn("سطر من السجلّ", hints)
        self.assertTrue(
            any("resolve_contact" in h for h in hints),
            hints,
        )

    def test_broken_provider_never_blocks_creation(self):
        def boom():
            raise RuntimeError("log unreadable")

        planner = FakePlanner(self.DRAFT)
        outcome = self.create(planner, means_hints_provider=boom)
        self.assertTrue(outcome.created, outcome)
        hints = planner.contexts[0].get("means_hints", [])
        self.assertTrue(any("resolve_contact" in h for h in hints))


class _FakeLLM:
    def __init__(self):
        self.messages = None

    def chat(self, messages, tools=None):
        self.messages = messages
        return {"text": '{"steps": []}'}


class TestPlannerRendering(unittest.TestCase):
    def test_hints_render_into_the_user_message(self):
        llm = _FakeLLM()
        adapter = LLMPlannerAdapter(llm)
        adapter.plan(
            "هدف",
            [],
            {
                "tool_args": {"web_search": ["query"]},
                "means_hints": ["تلميح وسيلة"],
            },
        )
        user = llm.messages[1]["content"]
        self.assertIn("سجلّ الوسائل", user)
        self.assertIn("تلميح وسيلة", user)

    def test_no_hints_no_block(self):
        llm = _FakeLLM()
        adapter = LLMPlannerAdapter(llm)
        adapter.plan("هدف", [], {"tool_args": {}})
        self.assertNotIn("سجلّ الوسائل", llm.messages[1]["content"])


class TestMeansLogUseCase(CreateCase):
    def _seed_plan(self):
        record = PlanRecord(
            plan_id="p_d4",
            goal="هدف",
            origin="interactive",
            steps=(
                PlanStepRecord(
                    step_id="s1",
                    intent="إضافة",
                    tool="calendar_add",
                    args={"title": "x"},
                    state="succeeded",
                    idempotency_key="p_d4:s1",
                    verify_outcome={"verdict": "verified"},
                    created_at=NOW_ISO,
                    updated_at=NOW_ISO,
                ),
            ),
            prior_actions=(),
            replans_used=0,
            replans_max=2,
            awaiting_step_id=None,
            escalated=False,
            created_at=NOW_ISO,
            updated_at=NOW_ISO,
            expires_at="2027-01-01T00:00:00+00:00",
            state="done",
        )
        self.store.save(record)

    def test_refresh_and_hints(self):
        self._seed_plan()
        log_path = Path(self._tmp.name) / "means_log.json"
        use_case = MeansLogUseCase(
            store=self.store, path=log_path, clock=fixed_clock
        )
        payload = use_case.refresh()
        self.assertTrue(log_path.exists())
        self.assertEqual(
            payload["best_per_family"]["calendar"], "calendar_add"
        )
        hints = use_case.hints()
        self.assertEqual(len(hints), 1)
        self.assertIn("calendar_add", hints[0])
        self.assertIn("1 نتيجة موثّقة", hints[0])

    def test_corrupt_log_yields_no_hints(self):
        log_path = Path(self._tmp.name) / "means_log.json"
        log_path.write_text("{not json", encoding="utf-8")
        use_case = MeansLogUseCase(
            store=self.store, path=log_path, clock=fixed_clock
        )
        self.assertEqual(use_case.hints(), [])


class _FakeMeansLog:
    def __init__(self, raises=False):
        self.calls = 0
        self._raises = raises

    def refresh(self):
        self.calls += 1
        if self._raises:
            raise RuntimeError("disk gone")


class TestRunRefreshesLog(CreateCase):
    def _run(self, means_log):
        planner = FakePlanner(
            plan_draft={
                "steps": [
                    draft_step(
                        "read_file", "قراءة", {"path": "x"}
                    )
                ]
            }
        )
        create = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
        )
        outcome = create.execute(
            CreatePlanRequest(
                goal="هدف", origin="interactive", min_steps=1
            )
        )
        assert outcome.created, outcome
        decompose = DecomposeStepUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            clock=fixed_clock,
            notifier=RecordingNotifier(),
        )
        run = RunPlanUseCase(
            dispatch=FakeDispatch(),
            verifier=ContractOkVerifier(),
            store=self.store,
            decompose=decompose,
            clock=fixed_clock,
            notifier=RecordingNotifier(),
            means_log=means_log,
        )
        return run.execute(outcome.plan)

    def test_run_refreshes_the_log_once(self):
        fake = _FakeMeansLog()
        outcome = self._run(fake)
        self.assertEqual(outcome.state.value, "done")
        self.assertEqual(fake.calls, 1)

    def test_raising_log_never_breaks_the_run(self):
        outcome = self._run(_FakeMeansLog(raises=True))
        self.assertEqual(outcome.state.value, "done")


if __name__ == "__main__":
    unittest.main()
