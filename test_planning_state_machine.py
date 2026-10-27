"""Decision 1 — plan/step state machine + derivation (spec §2).

Behavioral tests of the pure domain: the legal-transition table,
terminal immutability, plan invariants (single RUNNING, strict
order), and the derived plan state priority rules.
"""
import unittest
from datetime import datetime, timedelta, timezone

from domain.planning.derivation import (
    derive_plan_state,
    next_runnable_step,
)
from domain.planning.entities import Plan, PlanStep
from domain.planning.states import (
    BlockedReason,
    PlanState,
    StepState,
)
from domain.planning.transitions import (
    IllegalTransition,
    InvariantViolation,
    can_transition,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat(timespec="seconds")
FUTURE = (NOW + timedelta(hours=24)).isoformat(timespec="seconds")
PAST = (NOW - timedelta(hours=1)).isoformat(timespec="seconds")


def make_step(step_id, state=StepState.PENDING, plan_id="p_test",
              **kwargs):
    if state is StepState.BLOCKED and "blocked_reason" not in kwargs:
        kwargs["blocked_reason"] = BlockedReason.APPROVAL_DENIED
    return PlanStep(
        step_id=step_id,
        intent=f"خطوة {step_id}",
        tool="read_file",
        args={"path": "x"},
        state=state,
        idempotency_key=f"{plan_id}:{step_id}",
        **kwargs,
    )


def make_plan(steps, **kwargs):
    kwargs.setdefault("plan_id", "p_test")
    kwargs.setdefault("goal", "هدف تجريبي")
    kwargs.setdefault("origin", "interactive")
    kwargs.setdefault("created_at", NOW_ISO)
    kwargs.setdefault("updated_at", NOW_ISO)
    kwargs.setdefault("expires_at", FUTURE)
    return Plan(steps=steps, **kwargs)


class TestTransitionTable(unittest.TestCase):
    LEGAL = [
        (StepState.PENDING, StepState.RUNNING),
        (StepState.PENDING, StepState.BLOCKED),
        (StepState.PENDING, StepState.SKIPPED),
        (StepState.RUNNING, StepState.SUCCEEDED),
        (StepState.RUNNING, StepState.FAILED),
        (StepState.RUNNING, StepState.BLOCKED),
        (StepState.BLOCKED, StepState.PENDING),
        (StepState.BLOCKED, StepState.SKIPPED),
    ]

    ILLEGAL = [
        (StepState.SUCCEEDED, StepState.RUNNING),
        (StepState.FAILED, StepState.RUNNING),
        (StepState.SKIPPED, StepState.PENDING),
        (StepState.PENDING, StepState.SUCCEEDED),
        (StepState.PENDING, StepState.FAILED),
        (StepState.RUNNING, StepState.SKIPPED),
        (StepState.RUNNING, StepState.PENDING),
        (StepState.BLOCKED, StepState.RUNNING),
        (StepState.BLOCKED, StepState.SUCCEEDED),
        (StepState.PENDING, StepState.PENDING),
        (StepState.RUNNING, StepState.RUNNING),
    ]

    def test_legal_transitions_pass(self):
        for source, target in self.LEGAL:
            with self.subTest(source=source, target=target):
                self.assertTrue(can_transition(source, target))
                step = make_step("s1", state=source)
                step.transition(
                    target,
                    blocked_reason=(
                        BlockedReason.APPROVAL_DENIED
                        if target is StepState.BLOCKED
                        else None
                    ),
                )
                self.assertIs(step.state, target)

    def test_illegal_transitions_raise(self):
        for source, target in self.ILLEGAL:
            with self.subTest(source=source, target=target):
                self.assertFalse(can_transition(source, target))
                step = make_step("s1", state=source)
                with self.assertRaises(IllegalTransition):
                    step.transition(
                        target,
                        blocked_reason=(
                            BlockedReason.APPROVAL_DENIED
                            if target is StepState.BLOCKED
                            else None
                        ),
                    )

    def test_terminal_states_are_immutable(self):
        for terminal in (
            StepState.SUCCEEDED,
            StepState.FAILED,
            StepState.SKIPPED,
        ):
            for target in StepState:
                with self.subTest(terminal=terminal, target=target):
                    step = make_step("s1", state=terminal)
                    with self.assertRaises(IllegalTransition):
                        step.transition(
                            target,
                            blocked_reason=(
                                BlockedReason.APPROVAL_DENIED
                                if target is StepState.BLOCKED
                                else None
                            ),
                        )


class TestBlockedReasonInvariant(unittest.TestCase):
    def test_blocked_requires_reason(self):
        step = make_step("s1")
        with self.assertRaises(InvariantViolation):
            step.transition(StepState.BLOCKED)

    def test_blocked_carries_reason_and_unblock_clears_it(self):
        step = make_step("s1")
        step.transition(
            StepState.BLOCKED,
            blocked_reason=BlockedReason.APPROVAL_DENIED,
        )
        self.assertIs(
            step.blocked_reason, BlockedReason.APPROVAL_DENIED
        )
        step.transition(StepState.PENDING)
        self.assertIsNone(step.blocked_reason)

    def test_constructing_blocked_without_reason_raises(self):
        with self.assertRaises(InvariantViolation):
            PlanStep(
                step_id="s1",
                intent="x",
                tool="read_file",
                state=StepState.BLOCKED,
                idempotency_key="p_test:s1",
            )

    def test_constructing_nonblocked_with_reason_raises(self):
        with self.assertRaises(InvariantViolation):
            PlanStep(
                step_id="s1",
                intent="x",
                tool="read_file",
                state=StepState.PENDING,
                blocked_reason=BlockedReason.APPROVAL_DENIED,
                idempotency_key="p_test:s1",
            )


class TestPlanInvariants(unittest.TestCase):
    def test_empty_plan_rejected(self):
        with self.assertRaises(InvariantViolation):
            make_plan([])

    def test_duplicate_step_ids_rejected(self):
        with self.assertRaises(InvariantViolation):
            make_plan([make_step("s1"), make_step("s1")])

    def test_wrong_idempotency_key_rejected(self):
        bad = make_step("s1")
        bad.idempotency_key = "forged"
        with self.assertRaises(InvariantViolation):
            make_plan([bad])

    def test_depth_above_max_rejected(self):
        with self.assertRaises(InvariantViolation):
            make_plan([make_step("s1", depth=3)])

    def test_attempts_increment_on_running(self):
        step = make_step("s1")
        plan = make_plan([step])
        plan.transition_step("s1", StepState.RUNNING)
        self.assertEqual(step.attempts, 1)

    def test_second_running_step_rejected(self):
        plan = make_plan(
            [
                make_step("s1", state=StepState.RUNNING),
                make_step("s2"),
            ]
        )
        with self.assertRaises(InvariantViolation):
            plan.transition_step("s2", StepState.RUNNING)

    def test_strict_order_no_jumping(self):
        plan = make_plan([make_step("s1"), make_step("s2")])
        with self.assertRaises(InvariantViolation):
            plan.transition_step("s2", StepState.RUNNING)

    def test_no_jumping_over_blocked(self):
        plan = make_plan(
            [
                make_step("s1", state=StepState.BLOCKED),
                make_step("s2"),
            ]
        )
        with self.assertRaises(InvariantViolation):
            plan.transition_step("s2", StepState.RUNNING)
        self.assertIsNone(next_runnable_step(plan))


class TestNextRunnable(unittest.TestCase):
    def test_first_pending_is_runnable(self):
        plan = make_plan([make_step("s1"), make_step("s2")])
        self.assertEqual(next_runnable_step(plan).step_id, "s1")

    def test_succeeded_steps_are_passed(self):
        plan = make_plan(
            [
                make_step("s1", state=StepState.SUCCEEDED),
                make_step("s2"),
            ]
        )
        self.assertEqual(next_runnable_step(plan).step_id, "s2")

    def test_unresolved_failure_is_a_barrier(self):
        plan = make_plan(
            [
                make_step("s1", state=StepState.FAILED),
                make_step("s2"),
            ]
        )
        self.assertIsNone(next_runnable_step(plan))

    def test_resolved_failure_passes_to_substep(self):
        plan = make_plan(
            [
                make_step(
                    "s1",
                    state=StepState.FAILED,
                    resolved_by_decomposition=True,
                ),
                make_step("s1.1", depth=1, parent_step_id="s1"),
            ]
        )
        self.assertEqual(
            next_runnable_step(plan).step_id, "s1.1"
        )


class TestDerivation(unittest.TestCase):
    def derive(self, steps, **kwargs):
        return derive_plan_state(make_plan(steps, **kwargs), NOW)

    def test_running_wins(self):
        state = self.derive(
            [
                make_step("s1", state=StepState.RUNNING),
                make_step("s2", state=StepState.BLOCKED),
            ]
        )
        self.assertIs(state, PlanState.RUNNING)

    def test_awaiting_beats_blocked(self):
        state = self.derive(
            [
                make_step("s1", state=StepState.BLOCKED),
                make_step("s2"),
            ],
            awaiting_step_id="s2",
        )
        self.assertIs(state, PlanState.AWAITING_APPROVAL)

    def test_blocked(self):
        state = self.derive(
            [make_step("s1", state=StepState.BLOCKED)]
        )
        self.assertIs(state, PlanState.BLOCKED)

    def test_unresolved_failure_is_failed(self):
        state = self.derive(
            [
                make_step("s1", state=StepState.SUCCEEDED),
                make_step("s2", state=StepState.FAILED),
            ]
        )
        self.assertIs(state, PlanState.FAILED)

    def test_unresolved_failure_escalated_flag(self):
        state = self.derive(
            [make_step("s1", state=StepState.FAILED)],
            escalated=True,
        )
        self.assertIs(state, PlanState.ESCALATED)

    def test_resolved_failure_does_not_fail_plan(self):
        state = self.derive(
            [
                make_step(
                    "s1",
                    state=StepState.FAILED,
                    resolved_by_decomposition=True,
                ),
                make_step(
                    "s1.1",
                    state=StepState.SUCCEEDED,
                    depth=1,
                    parent_step_id="s1",
                ),
            ]
        )
        self.assertIs(state, PlanState.DONE)

    def test_done(self):
        state = self.derive(
            [
                make_step("s1", state=StepState.SUCCEEDED),
                make_step("s2", state=StepState.SKIPPED),
            ]
        )
        self.assertIs(state, PlanState.DONE)

    def test_pending(self):
        state = self.derive(
            [
                make_step("s1", state=StepState.SUCCEEDED),
                make_step("s2"),
            ]
        )
        self.assertIs(state, PlanState.PENDING)

    def test_expiry_beats_pending_and_blocked(self):
        self.assertIs(
            self.derive([make_step("s1")], expires_at=PAST),
            PlanState.EXPIRED,
        )
        self.assertIs(
            self.derive(
                [make_step("s1", state=StepState.BLOCKED)],
                expires_at=PAST,
            ),
            PlanState.EXPIRED,
        )

    def test_expiry_never_touches_done_or_escalated(self):
        self.assertIs(
            self.derive(
                [make_step("s1", state=StepState.SUCCEEDED)],
                expires_at=PAST,
            ),
            PlanState.DONE,
        )
        self.assertIs(
            self.derive(
                [make_step("s1", state=StepState.FAILED)],
                expires_at=PAST,
                escalated=True,
            ),
            PlanState.ESCALATED,
        )


if __name__ == "__main__":
    unittest.main()
