"""Plan (domain) <-> PlanRecord (DTO) conversion.

The ONLY place the two shapes meet (spec §3.1): the domain stays
persistence-ignorant, the records stay behavior-free. Enum values
cross as their string values; a stored derived-state string is
never read back as truth — plan_to_record recomputes it via the
domain derivation, record_to_plan ignores it.
"""
from __future__ import annotations

import sys
from datetime import datetime

from domain.planning.derivation import derive_plan_state
from domain.planning.entities import Plan, PlanStep, PriorAction
from domain.planning.states import BlockedReason, StepState

from features.planning.application.dto.planning import (
    PlanRecord,
    PlanStepRecord,
    PriorActionRecord,
)


def _step_to_record(step: PlanStep) -> PlanStepRecord:
    return PlanStepRecord(
        step_id=step.step_id,
        intent=step.intent,
        tool=step.tool,
        args=dict(step.args),
        state=step.state.value,
        depth=step.depth,
        parent_step_id=step.parent_step_id,
        attempts=step.attempts,
        idempotency_key=step.idempotency_key,
        result_ref=step.result_ref,
        error=step.error,
        blocked_reason=(
            step.blocked_reason.value
            if step.blocked_reason is not None
            else None
        ),
        outcome_unknown=step.outcome_unknown,
        resolved_by_decomposition=(
            step.resolved_by_decomposition
        ),
        verify=step.verify,
        compensate=step.compensate,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


def _step_from_record(record: PlanStepRecord) -> PlanStep:
    return PlanStep(
        step_id=record.step_id,
        intent=record.intent,
        tool=record.tool,
        args=dict(record.args),
        state=StepState(record.state),
        depth=record.depth,
        parent_step_id=record.parent_step_id,
        attempts=record.attempts,
        idempotency_key=record.idempotency_key,
        result_ref=record.result_ref,
        error=record.error,
        blocked_reason=(
            BlockedReason(record.blocked_reason)
            if record.blocked_reason is not None
            else None
        ),
        outcome_unknown=record.outcome_unknown,
        resolved_by_decomposition=(
            record.resolved_by_decomposition
        ),
        verify=record.verify,
        compensate=record.compensate,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def plan_to_record(plan: Plan, now: datetime) -> PlanRecord:
    derived = derive_plan_state(plan, now).value
    return PlanRecord(
        plan_id=plan.plan_id,
        goal=plan.goal,
        origin=plan.origin,
        steps=tuple(_step_to_record(s) for s in plan.steps),
        prior_actions=tuple(
            PriorActionRecord(
                tool=p.tool,
                args_hash=p.args_hash,
                result_ref=p.result_ref,
            )
            for p in plan.prior_actions
        ),
        replans_used=plan.replans_used,
        replans_max=plan.replans_max,
        awaiting_step_id=plan.awaiting_step_id,
        escalated=plan.escalated,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        expires_at=plan.expires_at,
        state=derived,
    )


def record_to_plan(record: PlanRecord, now: datetime) -> Plan:
    plan = Plan(
        plan_id=record.plan_id,
        goal=record.goal,
        origin=record.origin,
        steps=[_step_from_record(s) for s in record.steps],
        prior_actions=[
            PriorAction(
                tool=p.tool,
                args_hash=p.args_hash,
                result_ref=p.result_ref,
            )
            for p in record.prior_actions
        ],
        replans_used=record.replans_used,
        replans_max=record.replans_max,
        awaiting_step_id=record.awaiting_step_id,
        escalated=record.escalated,
        created_at=record.created_at,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
    )

    # Spec §2.5: a stored derived state that disagrees with the
    # recomputation is a data-integrity note, never a crash.
    derived = derive_plan_state(plan, now).value
    if record.state and record.state != derived:
        print(
            f"[planning] stored state {record.state!r} != "
            f"derived {derived!r} for plan {record.plan_id!r}; "
            "using derived",
            file=sys.stderr,
        )

    return plan
