"""Planner-draft validation (Decision 1 — pure domain).

Planner output is UNTRUSTED input (spec §4.6): a draft is either
accepted whole, exactly as validated, or rejected whole — never
silently edited into a different plan. The allowlist and the tool
argument schemas are passed in as data so this module stays pure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Union

from .entities import MAX_STEPS_PER_PLAN

#: The exact key set of one step draft — anything more or less is
#: a rejection (a draft may not smuggle state, ids or budgets).
STEP_DRAFT_KEYS = frozenset({"intent", "tool", "args"})

#: The exact key set of a plan draft.
PLAN_DRAFT_KEYS = frozenset({"steps"})


@dataclass(frozen=True)
class ValidatedStep:
    """One planner step that survived validation."""

    intent: str
    tool: str
    args: dict


@dataclass(frozen=True)
class PlanRejected:
    """A whole-draft rejection, with a machine-readable reason."""

    reason: str
    detail: str = ""


def validate_step_list(
    raw_steps,
    allowlist,
    tool_schemas: Mapping[str, frozenset],
    *,
    max_steps: int,
) -> Union[list, PlanRejected]:
    """Validate a raw list of step drafts.

    ``allowlist`` is the set of tool names a plan may use at all;
    ``tool_schemas`` maps a tool name to its allowed argument keys
    (light check only — full argument validation stays with
    Policy at dispatch time, spec §4.6.4).
    """
    if not isinstance(raw_steps, list):
        return PlanRejected("steps_not_a_list")

    if len(raw_steps) == 0:
        return PlanRejected("no_steps")

    if len(raw_steps) > max_steps:
        return PlanRejected(
            "too_many_steps",
            f"{len(raw_steps)} > {max_steps}",
        )

    validated = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            return PlanRejected(
                "step_not_an_object", f"index {index}"
            )

        keys = set(raw.keys())
        if keys != STEP_DRAFT_KEYS:
            return PlanRejected(
                "step_keys_mismatch",
                f"index {index}: {sorted(keys)}",
            )

        intent = raw["intent"]
        tool = raw["tool"]
        args = raw["args"]

        if not isinstance(intent, str) or not intent.strip():
            return PlanRejected(
                "intent_invalid", f"index {index}"
            )

        if not isinstance(tool, str) or tool not in allowlist:
            return PlanRejected(
                "tool_not_in_allowlist",
                f"index {index}: {tool!r}",
            )

        if not isinstance(args, dict):
            return PlanRejected(
                "args_not_an_object", f"index {index}"
            )

        allowed_keys = tool_schemas.get(tool, frozenset())
        extra = set(args.keys()) - set(allowed_keys)
        if extra:
            return PlanRejected(
                "args_outside_schema",
                f"index {index}: {tool} {sorted(extra)}",
            )

        validated.append(
            ValidatedStep(
                intent=intent.strip(),
                tool=tool,
                args=dict(args),
            )
        )

    return validated


def validate_plan_draft(
    draft,
    allowlist,
    tool_schemas: Mapping[str, frozenset],
) -> Union[list, PlanRejected]:
    """Validate a full plan draft ``{"steps": [...]}``.

    Returns the validated steps, or a PlanRejected. Bounds:
    1..MAX_STEPS_PER_PLAN steps (invariants §2.6.1 / §2.6.9).
    """
    if not isinstance(draft, dict):
        return PlanRejected("draft_not_an_object")

    keys = set(draft.keys())
    if keys != PLAN_DRAFT_KEYS:
        return PlanRejected(
            "draft_keys_mismatch", f"{sorted(keys)}"
        )

    return validate_step_list(
        draft["steps"],
        allowlist,
        tool_schemas,
        max_steps=MAX_STEPS_PER_PLAN,
    )
