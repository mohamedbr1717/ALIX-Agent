"""Pure Arabic renderers for plan state (spec §5.1).

Functions of (plan, now) only — no I/O, no state. Status icons
are fixed: ✅ done · ⏳ running · ⌛ waiting · ⛔ blocked ·
❌ failed · ⏭️ skipped. Step numbers render in Arabic-Indic
digits, as in the spec's example.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from domain.planning.derivation import derive_plan_state
from domain.planning.entities import Plan, PlanStep
from domain.planning.states import PlanState, StepState

_STEP_ICONS = {
    StepState.SUCCEEDED: "✅",
    StepState.RUNNING: "⏳",
    StepState.PENDING: "⌛",
    StepState.BLOCKED: "⛔",
    StepState.FAILED: "❌",
    StepState.SKIPPED: "⏭️",
}

_STATE_LABELS = {
    PlanState.PENDING: "قيد الانتظار",
    PlanState.RUNNING: "جارية",
    PlanState.AWAITING_APPROVAL: "بانتظار موافقة",
    PlanState.BLOCKED: "متوقفة (خطوة محظورة)",
    PlanState.DONE: "اكتملت",
    PlanState.FAILED: "فشلت",
    PlanState.ESCALATED: "مصعّدة إليك",
    PlanState.EXPIRED: "انتهت صلاحيتها",
}

_AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def _num(value: int) -> str:
    return str(value).translate(_AR_DIGITS)


def _step_line(index: int, step: PlanStep) -> str:
    icon = _STEP_ICONS[step.state]
    return f"{icon} {_num(index)}. {step.intent}"


def format_plan_steps(plan: Plan) -> str:
    return "\n".join(
        _step_line(index, step)
        for index, step in enumerate(plan.steps, start=1)
    )


def format_plan(plan: Plan, now: datetime) -> str:
    """Full status rendering (plan_status / final summaries)."""
    state = derive_plan_state(plan, now)
    label = _STATE_LABELS[state]
    lines = [
        f"🧭 خطة: {plan.goal}",
        f"الحالة: {label} — {plan.plan_id}",
        format_plan_steps(plan),
    ]
    return "\n".join(lines)


def format_plan_created(
    plan: Plan, approval_steps: int, now: datetime
) -> str:
    """Creation event (spec §5.1 event 1): step list + how many
    steps will ask for approval when reached."""
    header = f"🧭 خطة جديدة: {plan.goal}"
    count = f"الخطوات: {_num(len(plan.steps))}"
    if approval_steps:
        count += (
            f" — منها {_num(approval_steps)} "
            "تحتاج موافقتك عند بلوغها"
        )
    return "\n".join([header, count, format_plan_steps(plan)])


def format_decomposition(
    plan: Plan,
    failed_step: PlanStep,
    new_step_ids: List[str],
    now: datetime,
) -> str:
    return "\n".join(
        [
            f"🔧 فشلت خطوة وأُعيد تخطيطها: "
            f"«{failed_step.intent}»",
            f"قُسّمت إلى {_num(len(new_step_ids))} "
            "خطوات أبسط، والتنفيذ مستمر.",
            format_plan_steps(plan),
        ]
    )


def format_escalation(
    plan: Plan,
    failed_step: Optional[PlanStep],
    reason: str,
    now: datetime,
) -> str:
    """Escalation event (spec §4.5): what completed, what failed
    and why, and what was NOT done — plain language."""
    done = [
        s.intent
        for s in plan.steps
        if s.state is StepState.SUCCEEDED
    ]
    remaining = [
        s.intent
        for s in plan.steps
        if s.state
        in (StepState.PENDING, StepState.BLOCKED)
    ]
    lines = [f"🛑 توقفت خطة وتحتاج قرارك: {plan.goal}"]
    if done:
        lines.append(
            "اكتمل: " + "؛ ".join(done)
        )
    if failed_step is not None:
        lines.append(
            f"فشل: {failed_step.intent} — "
            f"{failed_step.error or reason}"
        )
    lines.append(f"السبب: {reason}")
    if remaining:
        lines.append(
            "لم يُفعَل بعد: " + "؛ ".join(remaining)
        )
    lines.append(f"معرّف الخطة: {plan.plan_id}")
    return "\n".join(lines)


def format_finished(plan: Plan, now: datetime) -> str:
    state = derive_plan_state(plan, now)
    if state is PlanState.DONE:
        header = f"🏁 اكتملت الخطة: {plan.goal}"
    else:
        header = (
            f"⏸️ توقفت الخطة ({_STATE_LABELS[state]}): "
            f"{plan.goal}"
        )
    return "\n".join([header, format_plan_steps(plan)])


def format_recovery(plans: List[Plan], now: datetime) -> str:
    """One combined startup digest (spec §3.3 rule 3)."""
    lines = [
        "♻️ بعد إعادة التشغيل: خطط كانت جارية وتوقفت "
        "بانتظار قرارك (لم يُستأنف شيء تلقائيًا):"
    ]
    for plan in plans:
        state = derive_plan_state(plan, now)
        lines.append(
            f"- {plan.goal} ({plan.plan_id}) — "
            f"{_STATE_LABELS[state]}"
        )
    return "\n".join(lines)
