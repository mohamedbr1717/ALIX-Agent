"""run_plan use case: the deterministic plan executor (spec §4.3).

Pure code loop — NO LLM inside. The model is invoked only by the
planner (creation / decomposition), never between steps: drift
from the plan is the top agent failure class in the MAST
literature, so step-to-step control stays deterministic here.

Every step dispatches ONLY through ToolDispatchPort, whose single
production adapter wraps the existing execute_tool/Policy path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from domain.planning.derivation import (
    derive_plan_state,
    next_runnable_step,
)
from domain.planning.entities import Plan, PlanStep
from domain.planning.states import BlockedReason, PlanState, StepState

from features.planning.application.mapping import plan_to_record
from features.planning.application.ports.plan_notifier import (
    PlanNotifierPort,
)
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.ports.verifier import (
    VerifierPort,
)
from features.planning.application.use_cases.decompose_step import (
    DecomposeStepUseCase,
)
from features.planning.application.use_cases.helpers import (
    iso,
    result_error_text,
    summarize_result,
)

#: The confirmation-denial contract of the existing pipeline:
#: core/agent/_tool_pipeline.py::execute_tool returns exactly
#: {"ok": False, "error": "رفض المستخدم تنفيذ العملية. ..."} when
#: confirm_tool() denies. A dedicated contract test pins this
#: prefix against the pipeline source so a silent change there
#: fails loudly here instead of misclassifying a human "no" as a
#: decomposable step failure.
APPROVAL_DENIED_ERROR_PREFIX = "رفض المستخدم تنفيذ العملية"


def is_approval_denial(result) -> bool:
    """True when a dispatch result is a human approval denial —
    as opposed to a step failure (spec §4.4)."""
    if not isinstance(result, dict):
        return False
    if result.get("cancelled") is True:
        return True
    error = str(result.get("error") or "")
    return error.startswith(APPROVAL_DENIED_ERROR_PREFIX)


@dataclass
class RunPlanOutcome:
    plan: Plan
    state: PlanState
    stopped_reason: str = ""


class RunPlanUseCase:
    """Application service: execute a plan to a stopping state."""

    def __init__(
        self,
        *,
        dispatch: ToolDispatchPort,
        verifier: VerifierPort,
        store: PlanStorePort,
        decompose: DecomposeStepUseCase,
        clock: Callable,
        notifier: Optional[PlanNotifierPort] = None,
    ):
        self._dispatch = dispatch
        self._verifier = verifier
        self._store = store
        self._decompose = decompose
        self._clock = clock
        self._notifier = notifier

    # ---------------------------------------------------------

    def execute(self, plan: Plan) -> RunPlanOutcome:
        stopped_reason = ""
        escalated_notified = False

        while True:
            now = self._clock()
            if (
                derive_plan_state(plan, now)
                is PlanState.EXPIRED
            ):
                stopped_reason = "expired"
                break

            step = next_runnable_step(plan)
            if step is None:
                break

            plan.transition_step(
                step.step_id, StepState.RUNNING, now=iso(now)
            )
            # The confirmation card (when the step needs one)
            # opens INSIDE the dispatch and may wait on the
            # owner: persist the wait pointer before dispatching
            # so crash recovery can see that this step was in
            # flight (spec §2.4 note + §3.3). The pointer is
            # cleared as soon as the dispatch returns.
            plan.awaiting_step_id = step.step_id
            self._save(plan)

            result = self._dispatch_one(step)

            plan.awaiting_step_id = None

            if result.get("ok"):
                if self._verifier.verify(step, result):
                    plan.transition_step(
                        step.step_id,
                        StepState.SUCCEEDED,
                        now=iso(self._clock()),
                    )
                    step.result_ref = summarize_result(result)
                else:
                    plan.transition_step(
                        step.step_id,
                        StepState.FAILED,
                        now=iso(self._clock()),
                    )
                    step.error = (
                        "فشل التحقق من نتيجة الخطوة "
                        "(قرار 2 سيعمّق هذا الحكم)."
                    )
                    self._save(plan)
                    if not self._decompose.execute(plan, step):
                        escalated_notified = plan.escalated
                        break
                self._save(plan)
                continue

            # --- not ok: denial vs failure (spec §4.4) ---
            if is_approval_denial(result):
                plan.transition_step(
                    step.step_id,
                    StepState.BLOCKED,
                    blocked_reason=(
                        BlockedReason.APPROVAL_DENIED
                    ),
                    now=iso(self._clock()),
                )
                # The card was answered (denied): the wait
                # pointer was already cleared above.
                self._save(plan)
                stopped_reason = "approval_denied"
                break

            plan.transition_step(
                step.step_id,
                StepState.FAILED,
                now=iso(self._clock()),
            )
            step.error = result_error_text(result)
            self._save(plan)

            if not self._decompose.execute(plan, step):
                escalated_notified = plan.escalated
                break

        final_state = derive_plan_state(plan, self._clock())
        self._save(plan)

        # Stopping is never silent (§4.3): the escalation notice
        # already carries the full picture when the hook escalated;
        # every other stop gets the finished notice.
        if self._notifier is not None and not escalated_notified:
            if final_state in (
                PlanState.DONE,
                PlanState.BLOCKED,
                PlanState.EXPIRED,
                PlanState.FAILED,
            ):
                self._notifier.finished(plan)

        return RunPlanOutcome(
            plan=plan,
            state=final_state,
            stopped_reason=stopped_reason,
        )

    # ---------------------------------------------------------

    def _dispatch_one(self, step: PlanStep) -> dict:
        try:
            result = self._dispatch.execute(
                step.tool, dict(step.args)
            )
        except Exception as exc:
            # The production path (execute_tool) never raises —
            # it converts exceptions into result dicts. A raising
            # adapter is treated as a plain step failure, not as
            # a crash of the executor.
            return {
                "ok": False,
                "error": f"تعذّر إرسال الأداة: {exc}",
            }
        if not isinstance(result, dict):
            return {
                "ok": False,
                "error": "نتيجة الأداة غير صالحة.",
            }
        return result

    def _save(self, plan: Plan) -> None:
        now = self._clock()
        plan.updated_at = iso(now)
        self._store.save(plan_to_record(plan, now))
