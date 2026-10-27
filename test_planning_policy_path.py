"""Decision 1 — Policy-path reuse (spec §4.4 / §7).

The executor must dispatch ONLY through the existing
execute_tool entrance, so a plan step meets the same gates as a
model-issued call. These tests drive the slice with a faithful
miniature of core/agent/_tool_pipeline.py::execute_tool (same
gate order, byte-identical denial result) and pin the slice's
denial marker against the real pipeline source — in this
environment the real agent module cannot be imported (its
python-dotenv dependency is absent), so the contract is pinned
textually instead of by import.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from domain.planning.states import BlockedReason, StepState

from features.planning.application.use_cases.run_plan import (
    APPROVAL_DENIED_ERROR_PREFIX,
)
from features.planning.composition import (
    build_planning_controller,
)

#: Byte-identical to the confirmation-denial result built in
#: core/agent/_tool_pipeline.py::execute_tool when
#: confirm_tool() returns False.
DENIAL_RESULT = {
    "ok": False,
    "error": (
        "رفض المستخدم تنفيذ العملية. "
        "أُلغيت هذه العملية نهائيًا — لا تستدعِ "
        "هذه الأداة مجددًا في هذه المحادثة."
    ),
}

LEVELS = {
    "list_files": "read",
    "read_file": "read",
    "calendar_delete": "destructive",
}
SCHEMAS = {
    "list_files": frozenset({"path"}),
    "read_file": frozenset({"path"}),
    "calendar_delete": frozenset({"event_id"}),
}
CONFIRMING = frozenset({"write", "execute", "destructive"})


class FakePipeline:
    """Miniature of execute_tool's gates, in its order:
    tool_allowed -> confirmation -> body. ``executed`` records
    ONLY post-confirmation body runs — the actual side effects."""

    def __init__(self, confirmer):
        self._confirmer = confirmer
        self.calls = []
        self.executed = []

    def execute(self, tool, args):
        self.calls.append((tool, dict(args)))
        if tool not in LEVELS:
            message = f"الأداة غير مسموحة: {tool}"
            return {
                "ok": False,
                "action": tool,
                "message": message,
                "error": message,
            }
        if LEVELS[tool] in CONFIRMING:
            if not self._confirmer(tool, args):
                return dict(DENIAL_RESULT)
        self.executed.append(tool)
        return {"ok": True, "message": f"تم تنفيذ {tool}"}


class FakeLLM:
    """DualLLM-shaped fake: plan drafts + decompose counter."""

    def __init__(self, plan_draft):
        self._plan_draft = plan_draft
        self.decompose_calls = 0

    def chat(self, messages, tools=None):
        if "فشلت خطوة" in messages[0]["content"]:
            self.decompose_calls += 1
            return {"content": '{"mode": "give_up"}'}
        return {
            "content": json.dumps(
                self._plan_draft, ensure_ascii=False
            )
        }


def draft(tool, intent="خطوة", args=None):
    return {
        "intent": intent,
        "tool": tool,
        "args": args if args is not None else {},
    }


class PolicyPathCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def build(self, plan_draft, confirmer):
        pipeline = FakePipeline(confirmer)
        llm = FakeLLM(plan_draft)
        controller = build_planning_controller(
            llm=llm,
            execute_tool=pipeline.execute,
            base_dir=Path(self._tmp.name),
            allowlist=frozenset(LEVELS),
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset({"calendar_delete"}),
            confirming_tools=frozenset(
                t for t, lvl in LEVELS.items() if lvl in CONFIRMING
            ),
        )
        return controller, pipeline, llm


class TestApprovalFlow(PolicyPathCase):
    def test_owner_denial_blocks_step_and_never_executes(self):
        controller, pipeline, llm = self.build(
            {
                "steps": [
                    draft(
                        "calendar_delete",
                        "احذف الحدث",
                        {"event_id": "42"},
                    )
                ]
            },
            confirmer=lambda tool, args: False,
        )
        outcome = controller.try_create_and_run(
            "احذف حدثًا",
            "interactive",
            prior_actions=[],
            min_steps=1,
        )

        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.state, "blocked")
        # The body (gateway) NEVER ran: denial precedes execution.
        self.assertEqual(pipeline.executed, [])
        self.assertEqual(len(pipeline.calls), 1)
        # A human "no" is not a step failure: no decomposition.
        self.assertEqual(llm.decompose_calls, 0)

        status = controller.handle_status(
            {"plan_id": outcome.plan_id}
        )
        step = status["plan"]["steps"][0]
        self.assertEqual(step["state"], "blocked")
        self.assertEqual(
            step["blocked_reason"], "approval_denied"
        )

    def test_owner_approval_executes_through_the_pipeline(self):
        controller, pipeline, llm = self.build(
            {
                "steps": [
                    draft(
                        "calendar_delete",
                        "احذف الحدث",
                        {"event_id": "42"},
                    )
                ]
            },
            confirmer=lambda tool, args: True,
        )
        outcome = controller.try_create_and_run(
            "احذف حدثًا",
            "interactive",
            prior_actions=[],
            min_steps=1,
        )
        self.assertEqual(outcome.state, "done")
        self.assertEqual(
            pipeline.executed, ["calendar_delete"]
        )


class TestScheduledOrigin(PolicyPathCase):
    def test_destructive_step_born_blocked_and_never_dispatched(
        self,
    ):
        controller, pipeline, llm = self.build(
            {
                "steps": [
                    draft("list_files", "اعرض", {"path": "w"}),
                    draft(
                        "calendar_delete",
                        "احذف",
                        {"event_id": "42"},
                    ),
                ]
            },
            confirmer=lambda tool, args: True,
        )
        outcome = controller.try_create_and_run(
            "مهمة مجدولة", "scheduled", prior_actions=[]
        )

        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.state, "blocked")
        # Only the read step was dispatched; the destructive
        # step was born BLOCKED (SCHEDULED_POLICY) and the
        # executor never reached the pipeline with it.
        self.assertEqual(
            [tool for tool, _ in pipeline.calls],
            ["list_files"],
        )
        status = controller.handle_status(
            {"plan_id": outcome.plan_id}
        )
        step = status["plan"]["steps"][1]
        self.assertEqual(step["state"], "blocked")
        self.assertEqual(
            step["blocked_reason"], "scheduled_policy"
        )


class TestSingleEntrance(PolicyPathCase):
    def test_every_step_enters_via_execute_tool_in_order(self):
        controller, pipeline, llm = self.build(
            {
                "steps": [
                    draft("list_files", "أولى", {"path": "w"}),
                    draft("read_file", "ثانية", {"path": "x"}),
                    draft("list_files", "ثالثة", {"path": "y"}),
                ]
            },
            confirmer=lambda tool, args: True,
        )
        outcome = controller.try_create_and_run(
            "هدف", "interactive", prior_actions=[]
        )
        self.assertEqual(outcome.state, "done")
        self.assertEqual(
            [tool for tool, _ in pipeline.calls],
            ["list_files", "read_file", "list_files"],
        )
        self.assertEqual(
            pipeline.executed,
            ["list_files", "read_file", "list_files"],
        )


class TestDenialContractPin(unittest.TestCase):
    def test_marker_matches_the_real_pipeline_source(self):
        source = Path(
            "core/agent/_tool_pipeline.py"
        ).read_text(encoding="utf-8")
        self.assertIn(APPROVAL_DENIED_ERROR_PREFIX, source)
        self.assertIn("أُلغيت هذه العملية نهائيًا", source)
        self.assertIn("tool_confirmation_denied", source)


class TestBridgeWiring(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_bridge_builds_a_working_full_controller(self):
        from core.feature_bridge import (
            build_planning_controller,
        )

        class FakePolicy:
            # Mirrors the real Policy surface used by the
            # bridge registry builder.
            tool_permissions = dict(LEVELS)
            tool_argument_schema = {
                name: {
                    "allowed": set(keys),
                    "required": set(),
                }
                for name, keys in SCHEMAS.items()
            }

        dispatched = []

        def spy_execute(tool, args):
            dispatched.append(tool)
            return {"ok": True, "message": "تم"}

        llm = FakeLLM(
            {
                "steps": [
                    draft("list_files", "أولى", {"path": "w"}),
                    draft("read_file", "ثانية", {"path": "x"}),
                ]
            }
        )
        controller = build_planning_controller(
            FakePolicy(),
            llm,
            None,
            spy_execute,
            Path(self._tmp.name),
        )
        outcome = controller.try_create_and_run(
            "هدف", "interactive", prior_actions=[]
        )
        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.state, "done")
        self.assertEqual(
            dispatched, ["list_files", "read_file"]
        )

    def test_migrated_handlers_register_the_plan_tools(self):
        from core.feature_bridge import (
            build_migrated_tool_handlers,
        )

        handlers = build_migrated_tool_handlers(
            MagicMock(), None
        )
        self.assertIn("plan_status", handlers)
        self.assertIn("plan_cancel", handlers)
        result = handlers["plan_status"]()
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "plan_status")
        denied = handlers["plan_cancel"]()
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["action"], "plan_cancel")


if __name__ == "__main__":
    unittest.main()
