"""recover_plans use case: startup crash normalization (spec §3.3).

Runs before any new work is accepted. Nothing is resumed and
nothing is re-dispatched: a step interrupted mid-flight is
BLOCKED for a human decision, because its dispatch may already
have produced a side effect (the UNKNOWN_OUTCOME reasoning that
Decision 3 will resolve with read-back).

Classification (a safety-motivated refinement of §3.3's rule
order, flagged in the build report): the executor persists the
awaiting pointer for the whole dispatch window, so a RUNNING
step cannot be proven un-executed — it is classified
INTERRUPTED_UNKNOWN_OUTCOME. APPROVAL_INTERRUPTED is used for
the spec's designed case: a step still PENDING whose plan's
awaiting pointer names it (the card died before dispatch).
"""
from __future__ import annotations

from typing import Callable, List, Optional

from domain.planning.entities import Plan
from domain.planning.states import BlockedReason, StepState

from features.planning.application.mapping import (
    plan_to_record,
    record_to_plan,
)
from features.planning.application.ports.plan_notifier import (
    PlanNotifierPort,
)
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.use_cases.helpers import iso


class RecoverPlansUseCase:
    """Normalize every stored plan after a crash/restart."""

    def __init__(
        self,
        *,
        store: PlanStorePort,
        clock: Callable,
        notifier: Optional[PlanNotifierPort] = None,
    ):
        self._store = store
        self._clock = clock
        self._notifier = notifier

    def execute(self) -> List[Plan]:
        now = self._clock()
        now_iso = iso(now)
        affected: List[Plan] = []

        for record in self._store.list_all():
            plan = record_to_plan(record, now)
            changed = False

            awaiting_id = plan.awaiting_step_id

            for step in plan.steps:
                if step.state is StepState.RUNNING:
                    step.transition(
                        StepState.BLOCKED,
                        blocked_reason=(
                            BlockedReason
                            .INTERRUPTED_UNKNOWN_OUTCOME
                        ),
                        now=now_iso,
                    )
                    step.outcome_unknown = True
                    changed = True
                elif (
                    step.state is StepState.PENDING
                    and awaiting_id == step.step_id
                ):
                    step.transition(
                        StepState.BLOCKED,
                        blocked_reason=(
                            BlockedReason.APPROVAL_INTERRUPTED
                        ),
                        now=now_iso,
                    )
                    changed = True

            if plan.awaiting_step_id is not None:
                # The card that pointer waited on died with the
                # process; the plan must not hang on it forever.
                plan.awaiting_step_id = None
                changed = True

            if changed:
                plan.updated_at = now_iso
                self._store.save(plan_to_record(plan, now))
                affected.append(plan)

        if affected and self._notifier is not None:
            # ONE combined digest, never a message per plan.
            self._notifier.recovered(affected)

        return affected
