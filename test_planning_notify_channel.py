"""Single delivery channel per turn (fix, 2026-11-01).

Live defect (owner's transcript, 2026-11-01 ~22:55): every
interactive clarification arrived TWICE — the formal
«❓ توضيح مطلوب قبل التنفيذ» text via the outbox, and a plain
«❓ {question}» as the turn's reply. Mechanism: production
wiring gives PlanNotifier an external sender, so _emit left
the buffer empty; PlanningController's clarification branch
found nothing to drain and synthesized its fallback reply —
the same question through the second channel.

Fix: PlanningController opens the notifier's buffering()
window for interactive turns — inside it, events buffer
even with a sender wired, and the reply is the single
channel. Scheduled turns are untouched: the outbox delivers
(their reply goes to the run log only).
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from features.planning.application.ports.planner import PlannerPort
from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.use_cases.cancel_plan import (
    CancelPlanUseCase,
)
from features.planning.application.use_cases.create_plan import (
    CreatePlanUseCase,
)
from features.planning.application.use_cases.decompose_step import (
    DecomposeStepUseCase,
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
from features.planning.application.use_cases.run_plan import (
    RunPlanUseCase,
)
from features.planning.infrastructure.adapters.contract_ok_verifier import (
    ContractOkVerifier,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)
from features.planning.interfaces.controllers.planning_controller import (
    PlanningController,
)
from features.planning.interfaces.notifier import PlanNotifier

NOW = datetime(2026, 11, 1, 23, 0, tzinfo=timezone.utc)


def fixed_clock():
    return NOW


class TestNotifierBuffering(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.notifier = PlanNotifier(
            sender=self.sent.append, clock=fixed_clock
        )

    def test_default_goes_external_only(self):
        self.notifier.clarification("هدف", "سؤال؟")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.notifier.drain(), [])

    def test_buffering_window_uses_buffer_only(self):
        with self.notifier.buffering():
            self.notifier.clarification("هدف", "سؤال؟")
        self.assertEqual(self.sent, [])
        texts = self.notifier.drain()
        self.assertEqual(len(texts), 1)
        self.assertIn("سؤال؟", texts[0])

    def test_buffering_nests_and_restores_on_error(self):
        with self.assertRaises(RuntimeError):
            with self.notifier.buffering():
                with self.notifier.buffering():
                    pass
                raise RuntimeError("boom")
        # Depth restored: external delivery works again.
        self.notifier.clarification("هدف", "سؤال؟")
        self.assertEqual(len(self.sent), 1)

    def test_sender_failure_still_falls_back_to_buffer(self):
        def broken(text):
            raise RuntimeError("no channel")

        notifier = PlanNotifier(sender=broken, clock=fixed_clock)
        notifier.clarification("هدف", "سؤال؟")
        self.assertEqual(len(notifier.drain()), 1)


ALLOWLIST = frozenset({"read_file", "write_file"})
SCHEMAS = {
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
}


class FakePlanner(PlannerPort):
    def __init__(self, plan_draft):
        self._plan_draft = plan_draft

    def plan(self, goal, prior_actions, context):
        return self._plan_draft

    def decompose(self, goal, failed_step, remaining_steps):
        return {"mode": "give_up"}


class _Dispatch(ToolDispatchPort):
    def execute(self, tool, args):
        return {"ok": True, "message": "تم"}


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonPlanStore(
            Path(self._tmp.name) / "plans.json"
        )
        self.sent = []
        # Production wiring: the notifier HAS an external
        # sender (the outbox the bot polls).
        self.notifier = PlanNotifier(
            sender=self.sent.append, clock=fixed_clock
        )

    def build(self, draft):
        planner = FakePlanner(draft)
        create = CreatePlanUseCase(
            planner=planner,
            store=self.store,
            allowlist=ALLOWLIST,
            tool_schemas=SCHEMAS,
            destructive_tools=frozenset(),
            confirming_tools=frozenset(),
            clock=fixed_clock,
            notifier=self.notifier,
        )
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
                notifier=self.notifier,
            ),
            clock=fixed_clock,
            notifier=self.notifier,
        )
        return PlanningController(
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
                notifier=self.notifier,
            ),
            create_plan=create,
            run_plan=run,
            notifier=self.notifier,
            clock=fixed_clock,
        )


class TestSingleDelivery(ControllerCase):
    def test_interactive_clarify_arrives_once_in_reply(self):
        controller = self.build({"clarify": "أي حساب بريد؟"})
        outcome = controller.try_create_and_run(
            "اقرأ البريد", "interactive"
        )
        self.assertTrue(outcome.handled)
        # Nothing leaked to the external channel...
        self.assertEqual(self.sent, [])
        # ...and the reply carries the formal text, once.
        self.assertEqual(
            outcome.reply_text.count("توضيح مطلوب قبل التنفيذ"), 1
        )
        self.assertEqual(outcome.reply_text.count("أي حساب بريد؟"), 1)

    def test_scheduled_clarify_arrives_once_via_outbox(self):
        controller = self.build({"clarify": "أي حساب بريد؟"})
        outcome = controller.try_create_and_run(
            "اقرأ البريد", "scheduled"
        )
        self.assertTrue(outcome.handled)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("توضيح مطلوب قبل التنفيذ", self.sent[0])
        # The reply (run log only) does not repeat the formal
        # text — it is the plain fallback line.
        self.assertNotIn(
            "توضيح مطلوب قبل التنفيذ", outcome.reply_text
        )

    def test_interactive_plan_events_stay_in_reply(self):
        draft = {"steps": [
            {"intent": "قراءة", "tool": "read_file",
             "args": {"path": "x"}},
            {"intent": "حفظ", "tool": "write_file",
             "args": {"path": "x", "content": "y"}},
        ]}
        controller = self.build(draft)
        outcome = controller.try_create_and_run(
            "اقرأ ثم احفظ", "interactive"
        )
        self.assertTrue(outcome.handled)
        self.assertEqual(self.sent, [])
        self.assertEqual(outcome.reply_text.count("🧭 خطة جديدة"), 1)


if __name__ == "__main__":
    unittest.main()
