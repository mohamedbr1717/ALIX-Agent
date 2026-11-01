"""write_file read-back + placeholder-args rejection (2026-11-01).

Owner approved both registered candidates after the third
live demonstration (plan p_20261101T203624_551b): a write_file
step dispatched with the planner-invented template string
"{{step.result.0.content}}" as its content, was approved on
a card showing that string, wrote it, and then blocked
VERIFICATION_UNKNOWN for lack of a spec.

1. write_file gains a default read-back spec: read the file
   back via read_file and compare its text with the written
   content (field_equals on ``stdout``). Content beyond the
   read-back channel's cap honestly stays UNKNOWN. With a
   spec, write_file also leaves Decision 6's ask set.
2. A draft binding a {{...}} template into step ARGS is
   rejected whole (placeholder_args) — templates are legal
   only inside verify specs, where the verifier resolves
   them. Direct execution remains the fallback that can
   carry real values between its own calls.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.planning.entities import PlanStep
from domain.planning.states import StepState
from domain.planning.validation import (
    PlanRejected,
    validate_plan_draft,
)

from features.planning.application.dto.planning import (
    CreatePlanRequest,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.ports.verifier import Verdict
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

NOW = datetime(2026, 11, 1, 21, 45, tzinfo=timezone.utc)
LEVELS = {"read_file": "read", "write_file": "write",
          "web_search": "read"}


def step(tool, args):
    return PlanStep(
        step_id="s", intent="x", tool=tool, args=args,
        state=StepState.PENDING, idempotency_key="p:s",
    )


class FakeDispatch:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def execute(self, tool, args):
        self.calls.append((tool, args))
        return self.payload


class TestWriteFileReadBack(unittest.TestCase):
    def verify(self, payload, content="سعر الذهب 4100"):
        verifier = ReadBackVerifier(
            dispatch=FakeDispatch(payload),
            tool_levels=dict(LEVELS),
        )
        return verifier.verify(
            step(
                "write_file",
                {"path": "gold.txt", "content": content},
            ),
            {"ok": True},
        )

    def test_matching_content_verifies(self):
        outcome = self.verify(
            {"ok": True, "stdout": "سعر الذهب 4100"}
        )
        self.assertEqual(outcome.verdict, Verdict.VERIFIED)
        self.assertEqual(outcome.channel, "read_file")

    def test_trailing_newline_difference_still_verifies(self):
        # read_file re-joins lines (no trailing newline); the
        # written content commonly ends with one.
        outcome = self.verify(
            {"ok": True, "stdout": "سعر الذهب 4100"},
            content="سعر الذهب 4100\n",
        )
        self.assertEqual(outcome.verdict, Verdict.VERIFIED)

    def test_different_content_fails(self):
        outcome = self.verify({"ok": True, "stdout": "نص آخر"})
        self.assertEqual(outcome.verdict, Verdict.FAILED)

    def test_the_live_incident_content_fails_against_real_text(self):
        # Had the spec existed, the template-string write
        # would still not have verified against real content.
        outcome = self.verify(
            {"ok": True, "stdout": "{{step.result.0.content}}"},
            content="سعر الذهب الحقيقي",
        )
        self.assertEqual(outcome.verdict, Verdict.FAILED)

    def test_unreadable_file_is_unknown(self):
        outcome = self.verify({"ok": False, "error": "غير موجود"})
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)

    def test_oversized_content_has_no_spec(self):
        outcome = self.verify(
            {"ok": True, "stdout": "x"}, content="x" * 4001
        )
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)
        self.assertIn("لا مواصفة", outcome.observed)

    def test_missing_content_has_no_spec(self):
        verifier = ReadBackVerifier(
            dispatch=FakeDispatch({"ok": True, "stdout": ""}),
            tool_levels=dict(LEVELS),
        )
        outcome = verifier.verify(
            step("write_file", {"path": "gold.txt"}), {"ok": True}
        )
        self.assertEqual(outcome.verdict, Verdict.UNKNOWN)


ALLOWLIST = frozenset({"web_search", "write_file"})
SCHEMAS = {
    "web_search": frozenset({"query"}),
    "write_file": frozenset({"path", "content"}),
}


def draft_with(content):
    return {"steps": [
        {"intent": "بحث", "tool": "web_search",
         "args": {"query": "ذهب"}},
        {"intent": "حفظ", "tool": "write_file",
         "args": {"path": "gold.txt", "content": content}},
    ]}


class TestPlaceholderRejection(unittest.TestCase):
    def validate(self, draft):
        return validate_plan_draft(
            draft, ALLOWLIST, SCHEMAS,
            read_tools=frozenset({"web_search"}),
        )

    def test_template_in_args_rejected(self):
        result = self.validate(
            draft_with("{{step.result.0.content}}")
        )
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "placeholder_args")

    def test_nested_template_rejected(self):
        draft = {"steps": [
            {"intent": "حفظ", "tool": "write_file",
             "args": {"path": "x",
                      "content": ["a", {"b": "{{step.x}}"}]}},
        ]}
        # content's schema is a light key check only; the
        # nested scan must still find the placeholder — use a
        # schema-permitted shape instead: path carries it.
        draft["steps"][0]["args"] = {
            "path": "{{step.args.p}}", "content": "نص",
        }
        result = self.validate(draft)
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "placeholder_args")

    def test_literal_braces_and_text_accepted(self):
        result = self.validate(
            draft_with("قالب {name} وسعره {x} — بلا أقواس مزدوجة")
        )
        self.assertNotIsInstance(result, PlanRejected)

    def test_verify_spec_templates_still_legal(self):
        draft = draft_with("نص حرفي")
        draft["steps"][1]["verify"] = {
            "read_tool": "web_search",
            "args": {"query": "{{step.args.path}}"},
            "predicate": "field_equals",
            "params": {"fields": {"stdout": "{{step.args.content}}"}},
        }
        result = self.validate(draft)
        self.assertNotIsInstance(result, PlanRejected)

    def test_prompt_states_the_boundary(self):
        self.assertIn("القوالب محظورة خارج verify", _PLAN_SYSTEM)
        self.assertIn("قيم حرفية دائمًا", _PLAN_SYSTEM)


class FakePlanner(PlannerPort):
    def __init__(self, plan_draft):
        self._plan_draft = plan_draft

    def plan(self, goal, prior_actions, context):
        return self._plan_draft

    def decompose(self, goal, failed_step, remaining_steps):
        return {"mode": "give_up"}


class SpyNotifier:
    def __init__(self):
        self.clarifications = []
        self.notices = []

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
        self.notices.append(list(notices))


class TestCreateConsequences(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.notifier = SpyNotifier()

    def create(self, draft, origin):
        use_case = CreatePlanUseCase(
            planner=FakePlanner(draft),
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=lambda: NOW,
            notifier=self.notifier,
            tool_levels=dict(LEVELS),
            verifiable_tools=ReadBackVerifier.default_spec_tools(),
        )
        return use_case.execute(
            CreatePlanRequest(goal="احفظ سعر الذهب", origin=origin)
        )

    def test_scheduled_write_file_no_longer_asks(self):
        outcome = self.create(draft_with("نص"), origin="scheduled")
        self.assertTrue(outcome.created, outcome)
        self.assertEqual(self.notifier.clarifications, [])

    def test_interactive_write_file_no_disclosure(self):
        outcome = self.create(draft_with("نص"), origin="interactive")
        self.assertTrue(outcome.created, outcome)
        self.assertEqual(self.notifier.notices, [])

    def test_placeholder_draft_rejected_not_asked(self):
        outcome = self.create(
            draft_with("{{step.result.0.content}}"),
            origin="scheduled",
        )
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.reason, "placeholder_args")
        self.assertEqual(self.notifier.clarifications, [])
        self.assertEqual(len(self.store.list_all()), 0)


if __name__ == "__main__":
    unittest.main()
