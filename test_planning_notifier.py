"""Decision 1 — PlanNotifier single-channel delivery.

Behavioral tests for the notifier's channel contract: each plan
event is delivered through exactly ONE channel — the injected
sender when present and healthy, otherwise the drainable buffer
(the CLI channel). Dual delivery duplicated every plan message
in Telegram, where the outbox sender and the controller's reply
both terminate in the same chat (live defect, 2026-10-29).
"""
import unittest
from datetime import datetime, timedelta, timezone

from domain.planning.entities import Plan, PlanStep
from domain.planning.states import StepState
from features.planning.interfaces.notifier import PlanNotifier

NOW = datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat(timespec="seconds")
FUTURE = (NOW + timedelta(hours=24)).isoformat(timespec="seconds")


def make_step(step_id, state=StepState.PENDING, plan_id="p_test"):
    return PlanStep(
        step_id=step_id,
        intent=f"خطوة {step_id}",
        tool="read_file",
        args={"path": "x"},
        state=state,
        idempotency_key=f"{plan_id}:{step_id}",
    )


def make_plan(steps):
    return Plan(
        plan_id="p_test",
        goal="هدف تجريبي",
        origin="interactive",
        steps=steps,
        created_at=NOW_ISO,
        updated_at=NOW_ISO,
        expires_at=FUTURE,
    )


def fixed_clock():
    return NOW


class TestSenderChannel(unittest.TestCase):
    def test_successful_sender_receives_each_event_once(self):
        sent = []
        notifier = PlanNotifier(sender=sent.append, clock=fixed_clock)
        plan = make_plan([make_step("s1")])
        notifier.created(plan, approval_steps=0)
        notifier.finished(plan)
        self.assertEqual(len(sent), 2)

    def test_successful_sender_buffers_nothing(self):
        sent = []
        notifier = PlanNotifier(sender=sent.append, clock=fixed_clock)
        plan = make_plan([make_step("s1")])
        notifier.created(plan, approval_steps=0)
        self.assertEqual(notifier.drain(), [])
        self.assertEqual(len(sent), 1)

    def test_every_event_type_uses_sender_only(self):
        sent = []
        notifier = PlanNotifier(sender=sent.append, clock=fixed_clock)
        ok = make_step("s1", StepState.SUCCEEDED)
        bad = make_step("s2", StepState.FAILED)
        plan = make_plan([ok, bad])
        notifier.created(plan, approval_steps=1)
        notifier.decomposed(plan, bad, ["s2a"])
        notifier.escalated(plan, bad, "سبب تجريبي")
        notifier.finished(plan)
        notifier.recovered([plan])
        self.assertEqual(len(sent), 5)
        self.assertEqual(notifier.drain(), [])


class TestBufferChannel(unittest.TestCase):
    def test_no_sender_buffers_for_drain(self):
        notifier = PlanNotifier(clock=fixed_clock)
        plan = make_plan([make_step("s1")])
        notifier.created(plan, approval_steps=0)
        texts = notifier.drain()
        self.assertEqual(len(texts), 1)
        self.assertIn("هدف تجريبي", texts[0])
        self.assertEqual(notifier.drain(), [])

    def test_failing_sender_falls_back_to_buffer(self):
        calls = []

        def boom(text):
            calls.append(text)
            raise RuntimeError("outbox down")

        notifier = PlanNotifier(sender=boom, clock=fixed_clock)
        plan = make_plan([make_step("s1", StepState.FAILED)])
        failed = plan.steps[0]
        notifier.escalated(plan, failed, "سبب تجريبي")  # must not raise
        self.assertEqual(len(calls), 1)
        texts = notifier.drain()
        self.assertEqual(len(texts), 1)
        self.assertIn("توقفت خطة", texts[0])

    def test_failing_sender_attempted_once_per_event(self):
        calls = []

        def boom(text):
            calls.append(text)
            raise RuntimeError("outbox down")

        notifier = PlanNotifier(sender=boom, clock=fixed_clock)
        plan = make_plan([make_step("s1")])
        notifier.created(plan, approval_steps=0)
        notifier.finished(plan)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(notifier.drain()), 2)


if __name__ == "__main__":
    unittest.main()
