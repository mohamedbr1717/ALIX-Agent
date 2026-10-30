"""decompose_step use case: the ADaPT failure hook (spec §4.5).

Called by the executor ONLY for a genuine step failure — never
for an approval denial (a human "no" is not a step failure).
The replan budget and the depth cap are checked HERE, in code,
before any model call; the budget is consumed by the call itself,
whatever it returns.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from domain.planning.entities import (
    MAX_DEPTH,
    MAX_STEPS_PER_PLAN,
    MAX_SUBSTEPS,
    MAX_TOTAL_STEPS,
    Plan,
    PlanStep,
    substep_id,
)
from domain.planning.states import StepState
from domain.planning.validation import (
    PlanRejected,
    validate_step_list,
)

from features.planning.application.mapping import plan_to_record
from features.planning.application.ports.plan_notifier import (
    PlanNotifierPort,
)
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.use_cases.helpers import iso


class DecomposeStepUseCase:
    """on_step_failed(plan, step) -> bool (True = keep running)."""

    def __init__(
        self,
        *,
        planner: PlannerPort,
        store: PlanStorePort,
        allowlist: frozenset,
        tool_schemas: dict,
        destructive_tools: frozenset,
        clock: Callable,
        notifier: Optional[PlanNotifierPort] = None,
        read_tools: frozenset = frozenset(),
    ):
        self._planner = planner
        self._store = store
        self._allowlist = allowlist
        self._tool_schemas = tool_schemas
        self._destructive_tools = destructive_tools
        self._clock = clock
        self._notifier = notifier
        self._read_tools = read_tools

    # ---------------------------------------------------------

    def execute(self, plan: Plan, step: PlanStep) -> bool:
        # Code-enforced guards BEFORE any model call (§4.5).
        if plan.replans_used >= plan.replans_max:
            return self._escalate(
                plan, step, "استُنفدت ميزانية إعادة التخطيط."
            )
        if step.depth >= MAX_DEPTH:
            return self._escalate(
                plan,
                step,
                "بلغت الخطوة أقصى عمق للتفكيك.",
            )

        # The budget is consumed by the call itself — a give-up
        # or a rejected draft is not a free retry (§4.5).
        plan.replans_used += 1

        remaining = [
            s
            for s in plan.steps
            if s.state is StepState.PENDING
        ]

        try:
            draft = self._planner.decompose(
                plan.goal, step, remaining
            )
        except Exception:
            self._save(plan)
            return self._escalate(
                plan, step, "تعذّر استدعاء المخطّط للتفكيك."
            )

        if not isinstance(draft, dict):
            self._save(plan)
            return self._escalate(
                plan, step, "أعاد المخطّط مسودة غير صالحة."
            )

        mode = draft.get("mode")
        if mode == "decompose":
            return self._apply_decompose(plan, step, draft)
        if mode == "rewrite_tail":
            return self._apply_rewrite_tail(plan, step, draft)

        # "give_up" — and anything unrecognized (fail-closed).
        self._save(plan)
        return self._escalate(
            plan, step, "استسلم المخطّط ولم يقترح بديلًا."
        )

    # ---------------------------------------------------------

    def _apply_decompose(
        self, plan: Plan, step: PlanStep, draft: dict
    ) -> bool:
        validated = validate_step_list(
            draft.get("steps"),
            self._allowlist,
            self._tool_schemas,
            max_steps=MAX_SUBSTEPS,
            read_tools=self._read_tools,
        )
        if isinstance(validated, PlanRejected):
            self._save(plan)
            return self._escalate(
                plan,
                step,
                f"رُفضت مسودة التفكيك ({validated.reason}).",
            )

        if len(plan.steps) + len(validated) > MAX_TOTAL_STEPS:
            self._save(plan)
            return self._escalate(
                plan,
                step,
                "تجاوز التفكيك الحد الأقصى لخطوات الخطة.",
            )

        now_iso = iso(self._clock())
        new_steps = [
            self._build_step(
                plan,
                substep_id(step.step_id, index),
                vstep,
                depth=step.depth + 1,
                parent_step_id=step.step_id,
                now_iso=now_iso,
            )
            for index, vstep in enumerate(validated, start=1)
        ]

        insert_at = plan.step_index(step.step_id) + 1
        plan.steps[insert_at:insert_at] = new_steps
        step.resolved_by_decomposition = True
        plan.validate_invariants()
        self._save(plan)

        if self._notifier is not None:
            self._notifier.decomposed(
                plan, step, [s.step_id for s in new_steps]
            )
        return True

    def _apply_rewrite_tail(
        self, plan: Plan, step: PlanStep, draft: dict
    ) -> bool:
        validated = validate_step_list(
            draft.get("steps"),
            self._allowlist,
            self._tool_schemas,
            max_steps=MAX_STEPS_PER_PLAN,
            read_tools=self._read_tools,
        )
        if isinstance(validated, PlanRejected):
            self._save(plan)
            return self._escalate(
                plan,
                step,
                f"رُفضت مسودة إعادة كتابة الذيل "
                f"({validated.reason}).",
            )

        if len(plan.steps) + len(validated) > MAX_TOTAL_STEPS:
            self._save(plan)
            return self._escalate(
                plan,
                step,
                "تجاوزت إعادة الكتابة الحد الأقصى "
                "لخطوات الخطة.",
            )

        now_iso = iso(self._clock())

        # Remaining PENDING steps are superseded (§4.5b).
        for other in plan.steps:
            if other.state is StepState.PENDING:
                other.transition(StepState.SKIPPED, now=now_iso)

        next_number = self._next_top_level_number(plan)
        new_steps = []
        for vstep in validated:
            step_id = f"s{next_number}"
            next_number += 1
            new_steps.append(
                self._build_step(
                    plan,
                    step_id,
                    vstep,
                    depth=step.depth,
                    parent_step_id=None,
                    now_iso=now_iso,
                )
            )

        plan.steps.extend(new_steps)
        # The new tail supersedes the failure too: without this
        # the failed step would barrier-block its own replacement.
        step.resolved_by_decomposition = True
        plan.validate_invariants()
        self._save(plan)

        if self._notifier is not None:
            self._notifier.decomposed(
                plan, step, [s.step_id for s in new_steps]
            )
        return True

    # ---------------------------------------------------------

    def _build_step(
        self,
        plan: Plan,
        step_id: str,
        vstep,
        *,
        depth: int,
        parent_step_id: Optional[str],
        now_iso: str,
    ) -> PlanStep:
        state = StepState.PENDING
        blocked_reason = None
        if (
            plan.origin == "scheduled"
            and vstep.tool in self._destructive_tools
        ):
            from domain.planning.states import BlockedReason

            state = StepState.BLOCKED
            blocked_reason = BlockedReason.SCHEDULED_POLICY
        return PlanStep(
            step_id=step_id,
            intent=vstep.intent,
            tool=vstep.tool,
            args=dict(vstep.args),
            state=state,
            depth=depth,
            parent_step_id=parent_step_id,
            idempotency_key=f"{plan.plan_id}:{step_id}",
            blocked_reason=blocked_reason,
            verify=vstep.verify,
            created_at=now_iso,
            updated_at=now_iso,
        )

    @staticmethod
    def _next_top_level_number(plan: Plan) -> int:
        highest = 0
        for step in plan.steps:
            head = step.step_id.split(".")[0]
            if head.startswith("s") and head[1:].isdigit():
                highest = max(highest, int(head[1:]))
        return highest + 1

    def _save(self, plan: Plan) -> None:
        now = self._clock()
        plan.updated_at = iso(now)
        self._store.save(plan_to_record(plan, now))

    def _escalate(
        self, plan: Plan, step: PlanStep, reason: str
    ) -> bool:
        plan.escalated = True
        self._save(plan)
        if self._notifier is not None:
            self._notifier.escalated(plan, step, reason)
        return False
