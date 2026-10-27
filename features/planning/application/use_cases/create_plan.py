"""create_plan use case: draft -> validate -> assemble -> save.

The planner is called exactly once. Its output is untrusted: the
domain validation either accepts the draft whole or rejects it
whole, and every identifier/timestamp/budget is assigned HERE by
code — never by the model (spec §4.2 / §4.6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, List, Optional

from domain.planning.entities import (
    PLAN_TTL_HOURS,
    Plan,
    PlanStep,
    PriorAction,
)
from domain.planning.states import BlockedReason, StepState
from domain.planning.validation import (
    PlanRejected,
    validate_plan_draft,
)

from features.planning.application.dto.planning import (
    CreatePlanRequest,
)
from features.planning.application.mapping import plan_to_record
from features.planning.application.ports.plan_notifier import (
    PlanNotifierPort,
)
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.use_cases.helpers import (
    hash_args,
    iso,
    new_plan_id,
    truncate_stored,
)


@dataclass
class CreatePlanOutcome:
    created: bool
    plan: Optional[Plan] = None
    reason: str = ""  # rejection reason when created is False
    detail: str = ""


class CreatePlanUseCase:
    """Application service: build a validated, persisted plan."""

    def __init__(
        self,
        *,
        planner: PlannerPort,
        store: PlanStorePort,
        allowlist: frozenset,
        tool_schemas: dict,
        destructive_tools: frozenset,
        confirming_tools: frozenset,
        clock: Callable,
        notifier: Optional[PlanNotifierPort] = None,
    ):
        self._planner = planner
        self._store = store
        self._allowlist = allowlist
        self._tool_schemas = tool_schemas
        self._destructive_tools = destructive_tools
        self._confirming_tools = confirming_tools
        self._clock = clock
        self._notifier = notifier

    def execute(
        self, request: CreatePlanRequest
    ) -> CreatePlanOutcome:
        prior_actions = [
            PriorAction(
                tool=str(tool),
                args_hash=hash_args(args or {}),
                result_ref=truncate_stored(result_text or ""),
            )
            for (tool, args, result_text) in request.prior_actions
        ]

        context = {
            "origin": request.origin,
            "tools": sorted(self._allowlist),
            "tool_args": {
                name: sorted(keys)
                for name, keys in self._tool_schemas.items()
            },
        }

        try:
            draft = self._planner.plan(
                request.goal, prior_actions, context
            )
        except Exception as exc:  # planner transport failure
            return CreatePlanOutcome(
                created=False,
                reason="planner_error",
                detail=type(exc).__name__,
            )

        validated = validate_plan_draft(
            draft, self._allowlist, self._tool_schemas
        )
        if isinstance(validated, PlanRejected):
            return CreatePlanOutcome(
                created=False,
                reason=validated.reason,
                detail=validated.detail,
            )

        if len(validated) < max(1, request.min_steps):
            return CreatePlanOutcome(
                created=False,
                reason="below_min_steps",
                detail=f"{len(validated)} steps",
            )

        now = self._clock()
        now_iso = iso(now)
        plan_id = new_plan_id(now)

        steps: List[PlanStep] = []
        for index, vstep in enumerate(validated, start=1):
            step_id = f"s{index}"
            blocked_reason = None
            state = StepState.PENDING
            if (
                request.origin == "scheduled"
                and vstep.tool in self._destructive_tools
            ):
                # Spec §4.4: a destructive step in a scheduled
                # plan is born BLOCKED and never reaches the
                # executor — stricter than the interactive path,
                # deliberately.
                state = StepState.BLOCKED
                blocked_reason = BlockedReason.SCHEDULED_POLICY
            steps.append(
                PlanStep(
                    step_id=step_id,
                    intent=vstep.intent,
                    tool=vstep.tool,
                    args=dict(vstep.args),
                    state=state,
                    depth=0,
                    parent_step_id=None,
                    idempotency_key=f"{plan_id}:{step_id}",
                    blocked_reason=blocked_reason,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
            )

        plan = Plan(
            plan_id=plan_id,
            goal=request.goal,
            origin=request.origin,
            steps=steps,
            prior_actions=prior_actions,
            replans_used=0,
            awaiting_step_id=None,
            escalated=False,
            created_at=now_iso,
            updated_at=now_iso,
            expires_at=iso(
                now + timedelta(hours=PLAN_TTL_HOURS)
            ),
        )

        self._store.save(plan_to_record(plan, now))

        if self._notifier is not None:
            approval_steps = sum(
                1
                for s in steps
                if s.state is StepState.PENDING
                and s.tool in self._confirming_tools
            )
            self._notifier.created(plan, approval_steps)

        return CreatePlanOutcome(created=True, plan=plan)
