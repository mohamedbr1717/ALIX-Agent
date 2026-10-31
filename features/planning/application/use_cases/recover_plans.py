"""recover_plans use case: startup crash normalization (spec §3.3).

Runs before any new work is accepted. Nothing is resumed and
nothing is re-dispatched: a step interrupted mid-flight is
BLOCKED for a human decision, because its dispatch may already
have produced a side effect. Decision 3 (owner's ruling,
2026-11-01) settled the two questions this use case left open:

- TIMING: recovery runs at process BOOT (agent entry points
  call it before accepting work), not lazily at first use; the
  in-run call remains as an idempotent safety net.
- READ-BACK: report-only. When a read-back verifier is wired,
  an interrupted step's effect is re-read and the outcome is
  RECORDED on the step (verify_outcome + an evidence line in
  step.error, surfaced by the recovery digest). The step stays
  BLOCKED either way — evidence informs the owner's decision,
  it never auto-resolves the step and never resumes the plan.

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
from features.planning.application.ports.verifier import (
    Verdict,
    VerifierPort,
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
        verifier: Optional[VerifierPort] = None,
    ):
        self._store = store
        self._clock = clock
        self._notifier = notifier
        self._verifier = verifier

    def execute(self) -> List[Plan]:
        # Decision 3: serialize recovery across the processes
        # sharing the store (bot + daemon) so normalization —
        # and therefore the single digest — happens exactly
        # once. The save inside the lock is the claim; the
        # digest is sent after the lock is released (a second
        # recovery then finds nothing left to normalize).
        lock = getattr(self._store, "locked", None)
        if lock is not None:
            with lock():
                affected = self._normalize()
        else:
            affected = self._normalize()

        if affected and self._notifier is not None:
            # ONE combined digest, never a message per plan.
            self._notifier.recovered(affected)

        return affected

    def _normalize(self) -> List[Plan]:
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
                    self._attach_readback_evidence(step)
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

        return affected

    # ---------------------------------------------------------

    _VERDICT_LABELS = {
        Verdict.VERIFIED: "الأثر مطابق للقراءة الراجعة",
        Verdict.FAILED: "الأثر مناقَض بالقراءة الراجعة",
        Verdict.UNKNOWN: "القراءة الراجعة غير محسومة",
    }

    def _attach_readback_evidence(self, step) -> None:
        """Decision 3, report-only: re-read the interrupted
        step's effect through the Decision-2 verifier and record
        what it says on the step. The step's BLOCKED state and
        outcome_unknown flag are NOT touched — the evidence is
        for the owner's decision, never an auto-resolution.
        The verifier is called with an empty result (there is
        no dispatch result at recovery time), so templates that
        need result data degrade to UNKNOWN, as designed."""
        if self._verifier is None:
            return
        try:
            outcome = self._verifier.verify(step, {})
        except Exception:
            return
        if outcome is None:
            return
        step.verify_outcome = outcome.to_record()
        label = self._VERDICT_LABELS.get(
            outcome.verdict, str(outcome.verdict)
        )
        step.error = (
            f"قراءة راجعة عند التعافي ({label}): "
            f"{outcome.observed}"
        )
