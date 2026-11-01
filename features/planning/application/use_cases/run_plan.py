"""run_plan use case: the deterministic plan executor (spec §4.3).

Pure code loop — NO LLM inside. The model is invoked only by the
planner (creation / decomposition), never between steps: drift
from the plan is the top agent failure class in the MAST
literature, so step-to-step control stays deterministic here.

Every step dispatches ONLY through ToolDispatchPort, whose single
production adapter wraps the existing execute_tool/Policy path.
"""
from __future__ import annotations

import re
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
    Verdict,
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
from features.planning.application.use_cases.means_log import (
    refresh_quietly,
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


#: Fetch-class tools: a fetch failure is an infrastructure
#: event (protected page, timeout), not a step that needs
#: smarter sub-steps (planner fetch-budget fix, 2026-10-31 —
#: plan p_20261030T232235_fdf7 burned its whole replan budget
#: decomposing one HTTP 202 into invented fetch/extract
#: steps). Fetch failures therefore NEVER reach the
#: decomposer: one alternate-URL retry, then a terminal
#: failure whose escalation carries the collected evidence.
FETCH_TOOLS = frozenset({"web_fetch"})

_URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")


def alternate_fetch_url(plan: Plan, failed_step: PlanStep):
    """First URL from a succeeded web_search in this plan (or
    in the prior actions the plan inherited) that the failed
    step has not already tried — None when there is none."""
    current = str((failed_step.args or {}).get("url") or "")
    texts = [
        s.result_ref
        for s in plan.steps
        if s.tool == "web_search"
        and s.state is StepState.SUCCEEDED
        and s.result_ref
    ]
    texts += [
        pa.result_ref
        for pa in plan.prior_actions
        if pa.tool == "web_search" and pa.result_ref
    ]
    for text in texts:
        for url in _URL_RE.findall(text):
            url = url.rstrip(".,;")
            if url and url != current:
                return url
    return None


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
        means_log=None,
        capability_checker=None,
    ):
        self._dispatch = dispatch
        self._verifier = verifier
        self._store = store
        self._decompose = decompose
        self._clock = clock
        self._notifier = notifier
        self._means_log = means_log
        self._capability_checker = capability_checker

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

            # Decision 5 pre-flight: a step whose tool the
            # capability ledger proves unavailable in this
            # context never dispatches — no approval card for
            # a dead means, no burned attempt, and (per the
            # means log's honesty rules) no failure recorded
            # for an attempt that was never made. The step
            # blocks as a capability fact and escalates.
            if self._capability_checker is not None:
                cap = None
                try:
                    cap = self._capability_checker(step.tool)
                except Exception:
                    cap = None
                if cap is not None and cap[0] == "unavailable":
                    plan.transition_step(
                        step.step_id,
                        StepState.BLOCKED,
                        blocked_reason=(
                            BlockedReason.CAPABILITY_UNAVAILABLE
                        ),
                        now=iso(now),
                    )
                    step.error = (
                        "القدرة غير متاحة في هذا السياق: "
                        f"{cap[1]}"
                    )
                    plan.escalated = True
                    self._save(plan)
                    if self._notifier is not None:
                        self._notifier.escalated(
                            plan,
                            step,
                            "القدرة غير متاحة في هذا السياق "
                            "(قرار 5).",
                        )
                    escalated_notified = True
                    stopped_reason = "capability_unavailable"
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

            if (
                not result.get("ok")
                and step.tool in FETCH_TOOLS
                and step.attempts == 1
            ):
                # Fetch-budget fix: exactly ONE alternate-URL
                # retry, inline, before the failure is recorded
                # — a different source for the same information,
                # never a decomposition into invented sub-steps.
                alt_url = alternate_fetch_url(plan, step)
                if alt_url is not None:
                    step.args = {**step.args, "url": alt_url}
                    result = self._dispatch_one(step)

            if result.get("ok"):
                outcome = self._verifier.verify(step, result)
                step.verify_outcome = outcome.to_record()
                if outcome.verdict is Verdict.VERIFIED:
                    plan.transition_step(
                        step.step_id,
                        StepState.SUCCEEDED,
                        now=iso(self._clock()),
                    )
                    step.result_ref = summarize_result(result)
                elif outcome.verdict is Verdict.FAILED:
                    # Decision 2 — owner's ruling (2026-10-30): a
                    # positively disproven effect escalates
                    # DIRECTLY. The decomposer is never consulted
                    # and no replan is consumed: re-dispatching
                    # blind after a false "success" could duplicate
                    # the side effect. The one-line contradicting
                    # evidence rides in step.error, which the
                    # escalation format already prints.
                    plan.transition_step(
                        step.step_id,
                        StepState.FAILED,
                        now=iso(self._clock()),
                    )
                    step.error = (
                        f"فشل التحقق: {outcome.observed}"
                    )
                    plan.escalated = True
                    self._save(plan)
                    if self._notifier is not None:
                        self._notifier.escalated(
                            plan,
                            step,
                            "فشل التحقق من نتيجة الخطوة (قرار 2).",
                        )
                    escalated_notified = True
                    stopped_reason = "verification_failed"
                    break
                else:  # Verdict.UNKNOWN
                    # No usable evidence: the step is NOT counted
                    # as succeeded — it blocks with outcome_unknown
                    # and the owner decides (Decision 2 spec §4).
                    plan.transition_step(
                        step.step_id,
                        StepState.BLOCKED,
                        blocked_reason=(
                            BlockedReason.VERIFICATION_UNKNOWN
                        ),
                        now=iso(self._clock()),
                    )
                    step.outcome_unknown = True
                    step.error = (
                        "تعذّر التحقق من نتيجة الخطوة: "
                        f"{outcome.observed}"
                    )
                    plan.escalated = True
                    self._save(plan)
                    if self._notifier is not None:
                        self._notifier.escalated(
                            plan,
                            step,
                            "تعذّر التحقق من نتيجة الخطوة (قرار 2).",
                        )
                    escalated_notified = True
                    stopped_reason = "verification_unknown"
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

            if step.tool in FETCH_TOOLS:
                # Fetch-budget fix: the decomposer is NEVER
                # consulted for a fetch failure and the replan
                # budget stays untouched. The step fails
                # terminally and the escalation carries what
                # the plan collected (format_escalation's
                # evidence section) — never an empty escalation.
                plan.escalated = True
                self._save(plan)
                if self._notifier is not None:
                    self._notifier.escalated(
                        plan,
                        step,
                        "فشل الجلب نهائيًا (محاولة بديلة واحدة "
                        "كحد أقصى) — لم يُفكَّك ولم تُمسّ ميزانية "
                        "إعادة التخطيط.",
                    )
                escalated_notified = True
                stopped_reason = "fetch_failed"
                break

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

        # Decision 4: the means log is derived state — rebuild
        # it from the store now that this run's outcomes are
        # persisted. Telemetry: a refresh failure never breaks
        # the run (refresh_quietly reports and moves on).
        refresh_quietly(self._means_log)

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
