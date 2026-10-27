"""Derived plan state + next-step selection (pure domain).

The derived state is the single source of truth for "where does
this plan stand" (spec §2.5): it is recomputed on every load and
every render; any stored value is informational only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .entities import Plan, PlanStep
from .states import PlanState, StepState


def _is_resolved_failure(step: PlanStep) -> bool:
    return (
        step.state is StepState.FAILED
        and step.resolved_by_decomposition
    )


def _is_satisfied(step: PlanStep) -> bool:
    """Steps that count as 'handled' for ordering/completion:
    succeeded, skipped, or failed-but-resolved-by-decomposition."""
    return (
        step.state in (StepState.SUCCEEDED, StepState.SKIPPED)
        or _is_resolved_failure(step)
    )


def next_runnable_step(plan: Plan) -> Optional[PlanStep]:
    """The next step the executor may run, or None.

    Strict order (spec §2.6.3): scan in list order; satisfied
    steps are passed over; the first PENDING step is runnable;
    anything else (RUNNING, BLOCKED, unresolved FAILED) is a
    barrier — later steps never jump over it.
    """
    for step in plan.steps:
        if _is_satisfied(step):
            continue
        if step.state is StepState.PENDING:
            return step
        return None
    return None


def _derive_base_state(plan: Plan) -> PlanState:
    """Spec §2.5 rules 2–7, in priority order."""
    if not plan.steps:
        return PlanState.PENDING

    if any(s.state is StepState.RUNNING for s in plan.steps):
        return PlanState.RUNNING

    if plan.awaiting_step_id:
        return PlanState.AWAITING_APPROVAL

    if any(s.state is StepState.BLOCKED for s in plan.steps):
        return PlanState.BLOCKED

    if any(
        s.state is StepState.FAILED
        and not s.resolved_by_decomposition
        for s in plan.steps
    ):
        return (
            PlanState.ESCALATED
            if plan.escalated
            else PlanState.FAILED
        )

    if all(_is_satisfied(s) for s in plan.steps):
        # NOTE (engineering judgment, flagged in the build
        # report): spec rule 6 literally names {SUCCEEDED,
        # SKIPPED}; a FAILED step resolved by decomposition must
        # also satisfy completion — rule 5 already carves it out
        # of FAILED, and without this a fully recovered plan
        # would derive PENDING forever and never complete.
        return PlanState.DONE

    return PlanState.PENDING


def derive_plan_state(plan: Plan, now: datetime) -> PlanState:
    """The plan's current state, derived from its steps.

    Rule 1 (expiry) applies only when the state derived without
    it would be PENDING, BLOCKED or AWAITING_APPROVAL, and never
    to an escalated plan (spec §9.4 default: escalated plans wait
    for the owner, they do not expire). An unparseable
    ``expires_at`` never expires a plan (tolerant, fail-safe).
    """
    base = _derive_base_state(plan)

    if (
        not plan.escalated
        and base
        in (
            PlanState.PENDING,
            PlanState.BLOCKED,
            PlanState.AWAITING_APPROVAL,
        )
        and plan.expires_at
    ):
        try:
            expires = datetime.fromisoformat(plan.expires_at)
        except ValueError:
            return base
        if expires.tzinfo is None:
            expires = expires.astimezone()
        if now > expires:
            return PlanState.EXPIRED

    return base
