"""Means data (Decision 4): tool families, declared rules,
and the pure outcome aggregation behind the means log.

Decision 4 (owner's rulings, 2026-11-01) rests on three honest
pieces, all data or pure functions — no intent classifier:

1. FAMILIES: every tool the planner may bind belongs to one
   effect family. The outcome log is keyed by (family, tool),
   never by the planner's free-text intent, which is unstable.
   A tool missing from the table is "other" — never guessed.

2. DECLARED RULES: a small owner-owned table. Context bans
   are mechanical facts (notify needs Termux:API, which a
   server does not have — the 2026-10-29 «لخّص» incident) and
   are ENFORCED at plan acceptance. Preference notes are
   standing advisory lines rendered into the planner's
   context (contacts resolve locally, never via web search —
   the other 2026-10-29 incident); they steer, they do not
   reject, because enforcing them would need intent keywords.

3. AGGREGATION: the means log is DERIVED from stored plans —
   what each step already recorded (state, verify_outcome,
   blocked_reason, outcome_unknown). It never rewrites
   history: a vacuously successful binding is recorded as the
   success it was (owner's ruling); the cure for a wrong
   means is a declared rule, not a falsified log. Policy
   denials are counted as denials, never as means failures.
"""
from __future__ import annotations

from typing import Iterable

#: Family -> member tools. Mirrors the feature layout and
#: Policy's tool table; extend HERE when a tool is added.
FAMILY_TOOLS = {
    "calendar": (
        "calendar_add", "calendar_list", "calendar_get",
        "calendar_delete",
    ),
    "mail": ("gmail_search", "gmail_read", "gmail_reply",
             "gmail_send"),
    "web": ("web_search", "web_fetch"),
    "browser": ("browse_page", "browser_fill", "browser_submit"),
    "contacts": ("resolve_contact",),
    "phone": ("phone_call", "send_sms"),
    "social": (
        "whatsapp_send", "facebook_post_text",
        "facebook_post_photo",
    ),
    "notify": ("notify",),
    "memory": ("remember_fact",),
    "files": (
        "list_files", "read_file", "search_files", "write_file",
        "create_directory", "delete_file", "verify_file",
    ),
    "system": (
        "system_info", "git_status", "run_python", "run_command",
    ),
    "code": ("repo_map", "search_code", "pack_context"),
    "scheduling": (
        "schedule_task", "list_scheduled_tasks",
        "cancel_scheduled_task",
    ),
    "planning": ("plan_status", "plan_cancel"),
    "history": ("history", "undo"),
}

TOOL_FAMILY = {
    tool: family
    for family, tools in FAMILY_TOOLS.items()
    for tool in tools
}

FAMILY_LABELS = {
    "calendar": "التقويم",
    "mail": "البريد",
    "web": "بحث الويب",
    "browser": "المتصفح",
    "contacts": "جهات الاتصال",
    "phone": "الهاتف",
    "social": "التواصل الاجتماعي",
    "notify": "الإشعارات",
    "memory": "الذاكرة",
    "files": "الملفات",
    "system": "النظام",
    "code": "الكود",
    "scheduling": "الجدولة",
    "planning": "التخطيط",
    "history": "السجلّ",
    "other": "أخرى",
}


def family_of(tool: str) -> str:
    """The tool's effect family — "other" when undeclared."""
    return TOOL_FAMILY.get(tool, "other")


#: Declared context bans: (tool, runtime tag) pairs that must
#: never appear in an accepted plan. Runtime tags come from
#: the composition probe ("server" / "termux"). Mechanical
#: capability facts only — no semantics, no keywords.
BANNED_TOOL_CONTEXTS = frozenset({
    # notify dispatches through Termux:API; on a server it
    # fails deterministically (2026-10-29, «لخّص» incident).
    ("notify", "server"),
})

#: Standing advisory preferences, rendered into the planner's
#: context verbatim (data, clearly not user instructions).
PREFERENCE_NOTES = (
    "جهات الاتصال تُحَلّ دائمًا بأداة resolve_contact من مخزن "
    "الجهات المحلي، ولا يُبحث عنها أبدًا في الويب.",
)


def aggregate_outcomes(plans: Iterable) -> dict:
    """Count recorded step outcomes per (family, tool).

    Pure: reads PlanStep records as stored. Counters:
    steps, succeeded, verified (Decision-2 verdict on a
    succeeded step), unknown_verdicts, failed (dispatch or
    verification failure — the step state is FAILED), blocked,
    denied (approval/Policy denial — NOT a means failure),
    outcome_unknown.
    """
    per_tool: dict = {}
    for plan in plans:
        for step in plan.steps:
            family = family_of(step.tool)
            key = (family, step.tool)
            row = per_tool.setdefault(key, {
                "family": family,
                "tool": step.tool,
                "steps": 0,
                "succeeded": 0,
                "verified": 0,
                "unknown_verdicts": 0,
                "failed": 0,
                "blocked": 0,
                "denied": 0,
                "outcome_unknown": 0,
            })
            row["steps"] += 1
            state = step.state.value
            # Verdicts are counted wherever the Decision-2
            # outcome was recorded: VERIFIED lands on succeeded
            # steps, UNKNOWN lands on the steps it blocked.
            outcome = step.verify_outcome or {}
            verdict = outcome.get("verdict")
            if verdict == "verified" and state == "succeeded":
                row["verified"] += 1
            elif verdict == "unknown":
                row["unknown_verdicts"] += 1
            if state == "succeeded":
                row["succeeded"] += 1
            elif state == "failed":
                row["failed"] += 1
            elif state == "blocked":
                row["blocked"] += 1
                reason = (
                    step.blocked_reason.value
                    if step.blocked_reason is not None
                    else ""
                )
                if reason == "approval_denied":
                    row["denied"] += 1
            if step.outcome_unknown:
                row["outcome_unknown"] += 1
    return per_tool


def best_tool_per_family(per_tool: dict) -> dict:
    """Per family, the tool with the strongest verified
    record (most verified, then fewest failed). Families with
    no verified step are absent — the log advises only from
    evidence."""
    best: dict = {}
    for (family, tool), row in per_tool.items():
        if row["verified"] <= 0:
            continue
        score = (row["verified"], -row["failed"])
        current = best.get(family)
        if current is None or score > current[0]:
            best[family] = (score, tool)
    return {family: tool for family, (_, tool) in best.items()}
