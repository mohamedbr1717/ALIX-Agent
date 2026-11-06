"""Planner-draft validation (Decision 1 — pure domain).

Planner output is UNTRUSTED input (spec §4.6): a draft is either
accepted whole, exactly as validated, or rejected whole — never
silently edited into a different plan. The allowlist and the tool
argument schemas are passed in as data so this module stays pure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Union

from .binding import (
    find_bindings,
    validate_bindings,
    without_bindings,
)
from .entities import MAX_STEPS_PER_PLAN

#: Planner-invented cross-step templates ({{step.result.0.…}}):
#: step args carry literal values — templates are resolved only
#: inside a verify spec, by the verifier. A draft binding one
#: into args would dispatch the literal string as the value
#: (three live incidents; the latest, 2026-11-01, put an
#: approval card in front of the owner asking to write
#: "{{step.result.0.content}}" into gold.txt). Such a draft is
#: rejected whole; the caller falls back to direct execution,
#: which CAN carry real values between its own sequential tool
#: calls. The ONE governed exception (2026-11-06) is the
#: step-output binding {{steps.sN.output}} — domain/planning/
#: binding.py owns its grammar; the scan below runs on args
#: with legal binding tokens removed, so that form is judged
#: by the binding validation and every other form by this one.
_PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")


def _contains_placeholder(value) -> bool:
    if isinstance(value, str):
        return bool(_PLACEHOLDER_RE.search(value))
    if isinstance(value, dict):
        return any(
            _contains_placeholder(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_placeholder(item) for item in value)
    return False

#: The exact key set of one step draft — anything more or less is
#: a rejection (a draft may not smuggle state, ids or budgets).
STEP_DRAFT_KEYS = frozenset({"intent", "tool", "args"})

#: Decision 2: the ONE additional key a step draft may carry — a
#: read-back verification spec. It is not state: it is validated
#: field-by-field below before it is accepted, exactly like args.
STEP_DRAFT_OPTIONAL_KEYS = frozenset({"verify"})

#: The closed predicate registry (decision-02 spec §2). The
#: read-back verifier evaluates exactly these names; anything
#: else is rejected here and degrades to UNKNOWN there.
VERIFY_PREDICATES = frozenset(
    {"field_equals", "exists_matching", "absent_matching"}
)

#: Keys a verify spec may carry — no more.
VERIFY_SPEC_KEYS = frozenset(
    {"read_tool", "channel", "args", "predicate", "params"}
)

#: The only internal read-back channel in v1 (decision-02 §3).
VERIFY_CHANNELS = frozenset({"memory"})

#: The exact key set of a plan draft.
PLAN_DRAFT_KEYS = frozenset({"steps"})


@dataclass(frozen=True)
class ValidatedStep:
    """One planner step that survived validation."""

    intent: str
    tool: str
    args: dict
    verify: Optional[dict] = None


@dataclass(frozen=True)
class PlanRejected:
    """A whole-draft rejection, with a machine-readable reason."""

    reason: str
    detail: str = ""


def validate_verify_spec(spec, read_tools) -> Optional[str]:
    """Validate one Decision-2 verify spec; None means accepted.

    ``read_tools`` is the set of tool names Policy classifies as
    read-level, passed in as data. A spec is accepted only when
    its read-back channel cannot write: either a read-level tool,
    or the internal memory channel (read-only by construction).
    """
    if not isinstance(spec, dict):
        return "spec_not_an_object"
    keys = set(spec.keys())
    if not keys <= VERIFY_SPEC_KEYS:
        return f"spec_keys_outside: {sorted(keys - VERIFY_SPEC_KEYS)}"
    has_tool = "read_tool" in spec
    has_channel = "channel" in spec
    if has_tool == has_channel:
        return "spec_needs_exactly_one_channel"
    if has_tool:
        read_tool = spec["read_tool"]
        if not isinstance(read_tool, str) or read_tool not in read_tools:
            return f"read_tool_not_read_level: {read_tool!r}"
    else:
        channel = spec["channel"]
        if channel not in VERIFY_CHANNELS:
            return f"channel_unknown: {channel!r}"
    predicate = spec.get("predicate")
    if predicate not in VERIFY_PREDICATES:
        return f"predicate_unknown: {predicate!r}"
    for key in ("args", "params"):
        if key in spec and not isinstance(spec[key], dict):
            return f"{key}_not_an_object"
    return None


def validate_step_list(
    raw_steps,
    allowlist,
    tool_schemas: Mapping[str, frozenset],
    *,
    max_steps: int,
    read_tools: frozenset = frozenset(),
    allow_bindings: bool = True,
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
        if not (
            STEP_DRAFT_KEYS <= keys
            <= STEP_DRAFT_KEYS | STEP_DRAFT_OPTIONAL_KEYS
        ):
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

        if _contains_placeholder(without_bindings(args)):
            return PlanRejected(
                "placeholder_args",
                f"index {index}: {tool} binds a {{{{...}}}} "
                "template into args — step args must be literal "
                "values; templates exist only inside verify specs",
            )

        if find_bindings(args):
            # Step-output binding (2026-11-06): the ONE legal
            # template family in args. References must name a
            # step EARLIER in this same draft (ids are assigned
            # s1..sN in draft order at creation, so this step —
            # 0-based `index` — may reference s1..s{index}).
            # Decomposition drafts pass allow_bindings=False:
            # sub-steps are literal-only in v1, by scope ruling.
            if not allow_bindings:
                return PlanRejected(
                    "binding_invalid",
                    f"index {index}: {tool} binds a step output "
                    "— bindings are not allowed in this draft",
                )
            prior_ids = {
                f"s{i}" for i in range(1, index + 1)
            }
            binding_error = validate_bindings(args, prior_ids)
            if binding_error is not None:
                return PlanRejected(
                    "binding_invalid",
                    f"index {index}: {binding_error}",
                )

        verify = None
        if "verify" in raw:
            reason = validate_verify_spec(raw["verify"], read_tools)
            if reason is not None:
                return PlanRejected(
                    "verify_spec_invalid",
                    f"index {index}: {reason}",
                )
            verify = dict(raw["verify"])

        validated.append(
            ValidatedStep(
                intent=intent.strip(),
                tool=tool,
                args=dict(args),
                verify=verify,
            )
        )

    return validated


def validate_plan_draft(
    draft,
    allowlist,
    tool_schemas: Mapping[str, frozenset],
    *,
    read_tools: frozenset = frozenset(),
    allow_bindings: bool = True,
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
        read_tools=read_tools,
        allow_bindings=allow_bindings,
    )
