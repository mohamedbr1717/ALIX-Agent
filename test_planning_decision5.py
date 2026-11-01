"""Decision 5 — the live capability ledger (2026-11-01).

Owner's rulings pinned here:
- States come from DECLARED data and PROBED facts only;
  observed outcomes never change a state (display lives in
  the Decision-4 means log, not here).
- Pre-flight: a step whose tool is proven unavailable in
  this context never dispatches, never asks for approval,
  and is never recorded as a means failure — it blocks as
  CAPABILITY_UNAVAILABLE and escalates.
- Probes are side-effect-free: PATH lookups, credential
  presence (names only), the router's own status report.
- "unknown" is a first-class state (llm_local liveness,
  meta_publish), never promoted without evidence.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.means import aggregate_outcomes
from domain.planning.states import BlockedReason

from features.planning.application.dto.planning import (
    CreatePlanRequest,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.use_cases.capabilities import (
    CapabilitiesUseCase,
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
from features.planning.infrastructure.adapters.llm_planner import (
    LLMPlannerAdapter,
)

NOW = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)

ALLOWLIST = frozenset(
    {"web_search", "notify", "read_file", "write_file",
     "whatsapp_send"}
)
SCHEMAS = {
    "web_search": frozenset({"query"}),
    "notify": frozenset({"message"}),
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
    "whatsapp_send": frozenset({"number", "message"}),
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


class SpyDispatch(ToolDispatchPort):
    def __init__(self):
        self.calls = []

    def execute(self, tool, args):
        self.calls.append(tool)
        return {"ok": True, "message": f"تم {tool}"}


class RecordingNotifier:
    def __init__(self):
        self.escalations = []

    def created(self, plan, approval_steps):
        pass

    def decomposed(self, plan, failed_step, new_step_ids):
        pass

    def escalated(self, plan, failed_step, reason):
        self.escalations.append((failed_step.step_id, reason))

    def finished(self, plan):
        pass

    def recovered(self, plans):
        pass


def make_ledger(tmp, **kw):
    defaults = dict(
        path=Path(tmp) / "capabilities.json",
        clock=fixed_clock,
        binary_prober=lambda name: None,
        env_reader=lambda name: None,
        llm_status_provider=None,
    )
    defaults.update(kw)
    return CapabilitiesUseCase(**defaults)


class TestLedgerStates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_missing_binary_is_unavailable(self):
        ledger = make_ledger(self._tmp.name)
        state, evidence = ledger.state_for("notify")
        self.assertEqual(state, "unavailable")
        self.assertIn("termux-notification", evidence)

    def test_present_binary_is_available(self):
        ledger = make_ledger(
            self._tmp.name, binary_prober=lambda name: "/x/" + name
        )
        self.assertEqual(ledger.state_for("phone_call")[0],
                         "available")

    def test_env_groups_presence(self):
        env = {"GMAIL_ADDRESS": "a@b.c", "GMAIL_APP_PASSWORD": "x"}
        ledger = make_ledger(
            self._tmp.name, env_reader=env.get
        )
        self.assertEqual(ledger.state_for("gmail_search")[0],
                         "available")
        self.assertEqual(ledger.state_for("calendar_add")[0],
                         "unavailable")

    def test_declared_states_need_no_probe(self):
        ledger = make_ledger(self._tmp.name)
        self.assertEqual(ledger.state_for("whatsapp_send")[0],
                         "unavailable")
        self.assertEqual(ledger.state_for("facebook_post_text")[0],
                         "unknown")

    def test_unlisted_tool_makes_no_claim(self):
        ledger = make_ledger(self._tmp.name)
        self.assertIsNone(ledger.state_for("web_search"))

    def test_llm_legs_from_router_status(self):
        status = {
            "remote_enabled": True,
            "remote_configured": True,
            "remote_provider": "groq",
            "remote_model": "gpt-oss-120b",
            "local_url": "http://127.0.0.1:8080",
            "local_model": "qwen",
        }
        ledger = make_ledger(
            self._tmp.name, llm_status_provider=lambda: status
        )
        payload = ledger.refresh()
        rows = {r["subject"]: r for r in payload["subjects"]}
        self.assertEqual(rows["llm_remote"]["state"], "available")
        # Liveness is NOT proven by a status report — the
        # local leg stays honestly unknown in v1.
        self.assertEqual(rows["llm_local"]["state"], "unknown")

    def test_llm_status_failure_is_unknown_not_crash(self):
        def boom():
            raise RuntimeError("router gone")

        ledger = make_ledger(
            self._tmp.name, llm_status_provider=boom
        )
        payload = ledger.refresh()
        rows = {r["subject"]: r for r in payload["subjects"]}
        self.assertEqual(rows["llm_remote"]["state"], "unknown")

    def test_planner_view_excludes_unavailable(self):
        ledger = make_ledger(self._tmp.name)
        excluded, notes = ledger.planner_view()
        self.assertIn("notify", excluded)
        self.assertIn("whatsapp_send", excluded)
        self.assertNotIn("facebook_post_text", excluded)
        self.assertTrue(any("notify" in n for n in notes))


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


class TestPlannerGating(CreateCase):
    VIEW = (frozenset({"notify"}), ["notify: unavailable — x"])

    def test_unavailable_tool_leaves_the_listing(self):
        planner = FakePlanner({"steps": [
            draft_step("read_file", "قراءة", {"path": "x"}),
            draft_step("write_file", "حفظ",
                       {"path": "x", "content": "y"}),
        ]})
        outcome = self.create(
            planner, capabilities_provider=lambda: self.VIEW
        )
        self.assertTrue(outcome.created, outcome)
        context = planner.contexts[0]
        self.assertNotIn("notify", context["tools"])
        self.assertNotIn("notify", context["tool_args"])
        self.assertEqual(
            context["capability_notes"], ["notify: unavailable — x"]
        )

    def test_draft_binding_unavailable_tool_is_rejected(self):
        planner = FakePlanner({"steps": [
            draft_step("web_search", "بحث", {"query": "q"}),
            draft_step("notify", "إشعار", {"message": "m"}),
        ]})
        outcome = self.create(
            planner, capabilities_provider=lambda: self.VIEW
        )
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.reason, "capability_unavailable")

    def test_broken_provider_never_blocks_creation(self):
        def boom():
            raise RuntimeError("ledger unreadable")

        planner = FakePlanner({"steps": [
            draft_step("read_file", "قراءة", {"path": "x"}),
            draft_step("write_file", "حفظ",
                       {"path": "x", "content": "y"}),
        ]})
        outcome = self.create(planner, capabilities_provider=boom)
        self.assertTrue(outcome.created, outcome)


class _FakeLLM:
    def __init__(self):
        self.messages = None

    def chat(self, messages, tools=None):
        self.messages = messages
        return {"text": '{"steps": []}'}


class TestPlannerRendering(unittest.TestCase):
    def test_capability_notes_render_as_data(self):
        llm = _FakeLLM()
        adapter = LLMPlannerAdapter(llm)
        adapter.plan(
            "هدف",
            [],
            {
                "tool_args": {"web_search": ["query"]},
                "capability_notes": ["notify: unavailable — x"],
            },
        )
        user = llm.messages[1]["content"]
        self.assertIn("سجلّ القدرات", user)
        self.assertIn("notify: unavailable", user)


class TestExecutorPreflight(CreateCase):
    def _build(self, checker):
        planner = FakePlanner({"steps": [
            draft_step("notify", "إشعار", {"message": "m"}),
            draft_step("read_file", "قراءة", {"path": "x"}),
        ]})
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
        self.dispatch = SpyDispatch()
        self.notifier = RecordingNotifier()
        decompose = DecomposeStepUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            clock=fixed_clock,
            notifier=self.notifier,
        )
        run = RunPlanUseCase(
            dispatch=self.dispatch,
            verifier=ContractOkVerifier(),
            store=self.store,
            decompose=decompose,
            clock=fixed_clock,
            notifier=self.notifier,
            capability_checker=checker,
        )
        return run.execute(outcome.plan), outcome.plan

    def test_unavailable_step_never_dispatches(self):
        outcome, plan = self._build(
            lambda tool: ("unavailable", "termux-notification غير موجود")
            if tool == "notify" else None
        )
        self.assertEqual(outcome.state.value, "blocked")
        self.assertEqual(outcome.stopped_reason,
                         "capability_unavailable")
        self.assertEqual(self.dispatch.calls, [])
        step = plan.steps[0]
        self.assertEqual(step.state.value, "blocked")
        self.assertEqual(step.blocked_reason,
                         BlockedReason.CAPABILITY_UNAVAILABLE)
        self.assertEqual(len(self.notifier.escalations), 1)
        # The means log's honesty: a capability block is a
        # block, never a failure.
        stats = aggregate_outcomes([plan])
        row = stats[("notify", "notify")]
        self.assertEqual((row["blocked"], row["failed"]), (1, 0))

    def test_no_claim_means_normal_run(self):
        outcome, plan = self._build(lambda tool: None)
        self.assertEqual(outcome.state.value, "done")
        self.assertEqual(
            self.dispatch.calls, ["notify", "read_file"]
        )


if __name__ == "__main__":
    unittest.main()
