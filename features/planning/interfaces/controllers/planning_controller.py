"""PlanningController (interfaces): thin translators only.

Two faces:
- Tool-facing: handle_status / handle_cancel for the
  plan_status / plan_cancel LLM tools (unified result dicts).
- Agent-facing: try_create_and_run (the round-3 escalation seam),
  recover (startup crash normalization), release_step (owner-only
  controller command — deliberately not an LLM tool, spec §5.2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from domain.planning.entities import Plan

from features.planning.application.dto.planning import (
    CancelPlanRequest,
    CreatePlanRequest,
    GetPlanRequest,
    ListPlansRequest,
)
from features.planning.application.use_cases.cancel_plan import (
    CancelPlanUseCase,
)
from features.planning.application.use_cases.create_plan import (
    CreatePlanUseCase,
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
from features.planning.interfaces import formatting
from features.planning.interfaces.notifier import PlanNotifier


@dataclass
class EscalationOutcome:
    """Result of an escalation attempt for the agent seam."""

    handled: bool
    reply_text: str = ""
    plan_id: str = ""
    state: str = ""
    reason: str = ""  # rejection reason when handled is False
    detail: str = ""


class PlanningController:
    def __init__(
        self,
        *,
        get_plan: GetPlanUseCase,
        list_plans: ListPlansUseCase,
        cancel_plan: CancelPlanUseCase,
        release_step: ReleaseStepUseCase,
        recover_plans: RecoverPlansUseCase,
        create_plan: Optional[CreatePlanUseCase] = None,
        run_plan: Optional[RunPlanUseCase] = None,
        notifier: Optional[PlanNotifier] = None,
        clock: Optional[Callable] = None,
    ):
        self._get_plan = get_plan
        self._list_plans = list_plans
        self._cancel_plan = cancel_plan
        self._release_step = release_step
        self._recover_plans = recover_plans
        self._create_plan = create_plan
        self._run_plan = run_plan
        self._notifier = notifier
        self._clock = clock

    # ---------------------------------------------------------
    # Tool-facing handlers
    # ---------------------------------------------------------

    def handle_status(self, arguments: dict) -> dict:
        arguments = arguments or {}
        plan_id = str(arguments.get("plan_id") or "").strip()
        if plan_id:
            return self._get_plan.execute(
                GetPlanRequest(plan_id=plan_id)
            )
        return self._list_plans.execute(
            ListPlansRequest(
                include_finished=bool(
                    arguments.get("include_finished", False)
                )
            )
        )

    def handle_cancel(self, arguments: dict) -> dict:
        arguments = arguments or {}
        return self._cancel_plan.execute(
            CancelPlanRequest(
                plan_id=str(
                    arguments.get("plan_id") or ""
                )
            )
        )

    # ---------------------------------------------------------
    # Agent-facing API
    # ---------------------------------------------------------

    def try_create_and_run(
        self,
        goal: str,
        origin: str,
        prior_actions=(),
        min_steps: int = 2,
    ) -> EscalationOutcome:
        """Create a plan for the remaining work and execute it.

        handled=False means "fall back to plain ReAct" — the
        spec's safe fallback (§4.1): planning is an improvement,
        never a new failure mode for tasks that worked before.
        """
        if self._create_plan is None or self._run_plan is None:
            return EscalationOutcome(
                handled=False, reason="planning_unavailable"
            )

        outcome = self._create_plan.execute(
            CreatePlanRequest(
                goal=goal,
                origin=origin,
                prior_actions=tuple(prior_actions),
                min_steps=min_steps,
            )
        )
        if not outcome.created:
            return EscalationOutcome(
                handled=False,
                reason=outcome.reason,
                detail=outcome.detail,
            )

        run_outcome = self._run_plan.execute(outcome.plan)

        texts = (
            self._notifier.drain()
            if self._notifier is not None
            else []
        )
        if not texts:
            texts = [
                formatting.format_plan(
                    run_outcome.plan, self._clock()
                )
            ]

        return EscalationOutcome(
            handled=True,
            reply_text="\n\n".join(texts),
            plan_id=run_outcome.plan.plan_id,
            state=run_outcome.state.value,
        )

    def recover(self) -> List[Plan]:
        """Startup crash normalization (spec §3.3)."""
        return self._recover_plans.execute()

    def release_step(self, plan_id: str, step_id: str) -> dict:
        """Owner-only unblock (controller command, not a tool)."""
        return self._release_step.execute(plan_id, step_id)

    def drain_notifications(self) -> List[str]:
        if self._notifier is None:
            return []
        return self._notifier.drain()
