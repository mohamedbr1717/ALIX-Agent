"""Ask-or-act data (Decision 6): the mechanical side of
"execute, or ask first?".

Decision 6 (owner's rulings, 2026-11-01) has exactly two
question sources, and this module is the mechanical one
(the other is the planner's own structured clarify reply):

- In a SCHEDULED context, a plan step that writes through a
  tool whose effect cannot be verified by read-back asks
  BEFORE it runs: today such a step dispatches and then
  blocks with an unknown outcome — the question is cheaper
  and more honest before the fact, when nobody is watching.
- In an INTERACTIVE context the same step executes without
  asking (the owner's ruling); the risk is DISCLOSED on the
  plan's creation notice instead — information, not a
  question, and never a gate.

The rule reads only facts: Policy's level table (data) and
the read-back verifier's default-spec coverage (data). No
text is classified and no confidence is scored. Destructive
steps are out of scope on purpose: scheduled ones are born
blocked (Decision 1) and interactive ones carry approval
cards — both already ask in their own way. Read steps are
out: their result is their evidence.
"""
from __future__ import annotations

import hashlib
from typing import List, Mapping

#: Single-ask principle (owner's ruling, 2026-11-01): one
#: request earns ONE question. A scheduled clarification for
#: the same goal is not re-delivered inside this cooldown —
#: a recurring task may ask again only on a genuinely new
#: occasion (after the window), never run after run.
ASK_REPEAT_COOLDOWN_DAYS = 7


def clarification_key(goal: str) -> str:
    """Stable identity of a clarification ask: the normalized
    goal text (the planner's question wording legitimately
    varies between runs; the goal is the durable intent)."""
    normalized = " ".join(str(goal or "").split()).casefold()
    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:24]

#: Levels whose effects change the world and so can outlive
#: a wrong guess — the levels the ask/disclose rule reads.
EFFECT_LEVELS = frozenset({"write", "execute"})

MAX_QUESTION_CHARS = 500


def unverifiable_write_steps(
    steps,
    *,
    tool_levels: Mapping[str, str],
    verifiable_tools: frozenset,
) -> list:
    """Validated steps that write with no way to verify.

    A step is verifiable when it carries its own Decision-2
    verify spec, or when its tool has a default read-back
    spec. Anything else at write/execute level is a hit.
    """
    hits = []
    for step in steps:
        if tool_levels.get(step.tool, "") not in EFFECT_LEVELS:
            continue
        if getattr(step, "verify", None) is not None:
            continue
        if step.tool in verifiable_tools:
            continue
        hits.append(step)
    return hits


def scheduled_ask_question(hits) -> str:
    """The one mechanical question, composed from facts."""
    parts = [
        f"الخطوة «{step.intent}» تستخدم {step.tool}"
        for step in hits
    ]
    return (
        "قبل التنفيذ المجدول — "
        + "؛ ".join(parts)
        + ": كتابة غير قابلة للتحقق بالقراءة الراجعة، فإن "
        "نُفّذت ستُحجب نتيجتها «مجهولة» بعد التنفيذ. "
        "هل تريد تنفيذها كما هي، أم تعديل المهمة أو إضافة "
        "مواصفة تحقق؟"
    )[:MAX_QUESTION_CHARS]


def disclosure_lines(hits) -> List[str]:
    """Interactive disclosure: the same facts, stated — not
    asked — on the creation notice."""
    return [
        f"⚠️ تنبيه (قرار 6): الخطوة «{step.intent}» "
        f"({step.tool}) كتابة غير قابلة للتحقق بالقراءة "
        "الراجعة — ستُنفَّذ، وإن تعذّر إثبات أثرها ستُحجب "
        "نتيجتها «مجهولة»."
        for step in hits
    ]
