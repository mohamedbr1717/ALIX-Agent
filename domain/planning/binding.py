"""Step-output binding (owner's ruling 2026-11-06, option ج).

A plan step may reference the OUTPUT of an earlier step in the
same plan, in exactly one strict form:

    {{steps.sN.output}}

where ``sN`` is the referenced step's id (steps are numbered
s1..sN in draft order at creation). The executor substitutes the
referenced step's stored ``output_text`` at dispatch time.

Why this form: the planner model reaches for cross-step templates
instinctively — the 2026-11-01 incident put the literal string
``{{step.result.0.content}}`` on an approval card, and the
2026-11-06 incident shipped the promissory prose placeholder
«[سيتم استخراج البيانات من الخطوة السابقة]» into a file whose
plan then reported ✅✅✅. The 82a1063 guard rejects every
``{{...}}`` form in args (``placeholder_args``); this module
legalizes ONE governed form out of that family and leaves every
other form rejected exactly as before.

Doctrine (fail-closed throughout):

- A binding is validated at draft acceptance: the reference must
  name a step that appears EARLIER in the same draft. Anything
  else rejects the whole draft (``binding_invalid``), exactly as
  ``placeholder_args`` rejects whole.
- Resolution happens only at dispatch, from values actually
  captured. A reference whose source step did not succeed, or
  whose output was never captured, blocks the bound step
  (``BINDING_UNAVAILABLE``) — the token is never dispatched
  literally and never substituted with an empty string.
- A bound step's args are not final at plan acceptance, so under
  Decision 7's own ruling (args materialized after approval face
  their own card) a bound step is never consent-stamped; its
  execution card shows the MATERIALIZED args.

This module is pure stdlib so the validator, the executor and the
creation use case share ONE grammar — a second implementation
would be a second source of truth.
"""
from __future__ import annotations

import re
from typing import Mapping, Optional

#: The one legal binding token. Anchored to the exact shape:
#: ``{{steps.s<digits>.output}}`` — no spaces, no field access,
#: no other root. Anything else inside ``{{...}}`` stays under
#: the placeholder rejection.
BINDING_RE = re.compile(r"\{\{steps\.(s[0-9]+)\.output\}\}")

#: Stored-output cap: how much of a step's tool result is kept
#: on the step record as its bindable output. Deliberately larger
#: than the 500-char result summary (a summary is for display;
#: an output is data), still a hard bound (resource discipline).
MAX_BINDING_CHARS = 8000

#: A single resolved string argument longer than this blocks the
#: bound step instead of dispatching an unbounded value.
MAX_RESOLVED_ARG_CHARS = 16000


class BindingResolutionError(Exception):
    """Resolution failed closed. ``kind`` is "unavailable" (a
    referenced output is missing) or "too_large" (a resolved
    value exceeds the bound); ``detail`` names the reference or
    the offending size for the step's error record."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def _walk_strings(value):
    """Yield every string inside a nested args structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def find_bindings(value) -> list:
    """Referenced step ids, in order of appearance (duplicates
    kept — validation and resolution both walk the same list)."""
    refs = []
    for text in _walk_strings(value):
        refs.extend(BINDING_RE.findall(text))
    return refs


def step_uses_bindings(value) -> bool:
    """True when any string in the structure carries a legal
    binding token."""
    return any(
        BINDING_RE.search(text) for text in _walk_strings(value)
    )


def without_bindings(value):
    """A copy of the structure with every legal binding token
    removed from its strings. Used by draft validation to scan
    for ILLEGAL templates without flagging the legal form: what
    remains after removal must contain no ``{{...}}`` at all."""
    if isinstance(value, str):
        return BINDING_RE.sub("", value)
    if isinstance(value, dict):
        return {
            key: without_bindings(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [without_bindings(item) for item in value]
    return value


def validate_bindings(value, prior_step_ids) -> Optional[str]:
    """None when every reference names a step in
    ``prior_step_ids`` (the steps BEFORE this one in the same
    draft); otherwise a detail string naming the first bad
    reference."""
    for ref in find_bindings(value):
        if ref not in prior_step_ids:
            return (
                f"binding {{{{steps.{ref}.output}}}} does not "
                "name an earlier step in this draft"
            )
    return None


def _resolve_string(text: str, outputs: Mapping[str, str]) -> str:
    def _sub(match: "re.Match") -> str:
        ref = match.group(1)
        if ref not in outputs:
            raise BindingResolutionError(
                "unavailable", f"steps.{ref}.output"
            )
        return outputs[ref]

    resolved = BINDING_RE.sub(_sub, text)
    if len(resolved) > MAX_RESOLVED_ARG_CHARS:
        raise BindingResolutionError(
            "too_large",
            f"resolved value is {len(resolved)} chars "
            f"(cap {MAX_RESOLVED_ARG_CHARS})",
        )
    return resolved


def resolve_args(args: dict, outputs: Mapping[str, str]) -> dict:
    """Return a NEW args dict with every binding token replaced
    by the referenced step's captured output.

    ``outputs`` maps step_id -> output_text for steps that
    succeeded AND had their output captured. Raises
    BindingResolutionError on the first unresolvable reference
    or oversized value — the caller blocks the step; a partially
    resolved dict is never returned.
    """

    def _walk(value):
        if isinstance(value, str):
            return _resolve_string(value, outputs)
        if isinstance(value, dict):
            return {
                key: _walk(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [_walk(item) for item in value]
        return value

    return _walk(dict(args or {}))
