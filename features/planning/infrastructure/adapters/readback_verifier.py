"""Read-back verifier (Decision 2): distrust ``ok``, re-read.

Where ``ContractOkVerifier`` trusts the tool result's contract,
this verifier proves the step's effect through an independent
read-back channel and returns a three-valued verdict:

- VERIFIED — the read-back positively matches the intended effect.
- FAILED — the read-back succeeded and positively contradicts
  the claimed effect (the نبراس lesson, spec §0: a step bound to
  the wrong tool said ok and the plan believed it).
- UNKNOWN — the read-back could not be performed, its evidence
  is unusable, a template could not be resolved, or the step has
  no verification spec at all. UNKNOWN never masquerades as
  success: the executor blocks the step with outcome_unknown.

Channels (decision-02 spec §2/§3): external state is re-read
through a read-level TOOL dispatched on the same
ToolDispatchPort/Policy path as plan steps (calendar_get for
calendar effects); internal state (the agent's own memory store)
is re-read through an internal provider that re-opens the store
and searches it — a different code path from the write result,
with a weaker independence level (same process/disk), disclosed
in the spec's default table.

The verifier NEVER re-executes the step's own tool and never
raises into the executor: any internal error degrades to UNKNOWN.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional

from domain.planning.entities import PlanStep

from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)
from features.planning.application.ports.verifier import (
    VerificationOutcome,
    Verdict,
    VerifierPort,
)

try:
    from zoneinfo import ZoneInfo

    _LOCAL_TZ = ZoneInfo("Africa/Casablanca")
except Exception:  # tzdata unavailable (rare)
    _LOCAL_TZ = timezone(timedelta(hours=1))

_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")

#: Steps whose effect needs no read-back: pure reads (their result
#: IS the evidence) and notify (no readable world state). Levels
#: come from Policy's own table, injected as data.
_EXEMPT_BY_NAME = frozenset({"notify"})

#: Default read-back specs by step tool (decision-02 spec §3).
#: calendar_add prefers the by-id read; the day-window list spec
#: is built dynamically when the add result carries no event_id.
_ADD_GET_SPEC = {
    "read_tool": "calendar_get",
    "args": {"event_id": "{{step.result.event_id}}"},
    "predicate": "field_equals",
    "params": {
        "fields": {
            "event.title": "{{step.args.title}}",
            "event.start": "{{step.args.start}}",
        }
    },
}
_DELETE_SPEC = {
    "read_tool": "calendar_get",
    "args": {"event_id": "{{step.args.event_id}}"},
    "predicate": "field_equals",
    "params": {"fields": {"found": False}},
}
_MEMORY_SPEC = {
    "channel": "memory",
    "args": {"query": "{{step.args.fact}}"},
    "predicate": "exists_matching",
    "params": {"match": {"text": "{{step.args.fact}}"}},
}


class _Unresolvable(Exception):
    """A template referenced data the step/result does not have."""


def _dig(payload, path: str):
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _parse_instant(value) -> Optional[datetime]:
    if not isinstance(value, str) or "T" not in value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # The gateway's own convention: naive means local time.
        parsed = parsed.replace(tzinfo=_LOCAL_TZ)
    return parsed


def _values_equal(actual, expected) -> bool:
    if actual == expected:
        return True
    if isinstance(actual, str) and isinstance(expected, str):
        if actual.strip() == expected.strip():
            return True
        left = _parse_instant(actual)
        right = _parse_instant(expected)
        if left is not None and right is not None:
            return left == right
    return False


def _resolve_templates(value, context):
    if isinstance(value, str):
        def replace(match):
            resolved = _dig(context, match.group(1))
            if resolved is None:
                raise _Unresolvable(match.group(1))
            return str(resolved)

        return _TEMPLATE_RE.sub(replace, value)
    if isinstance(value, dict):
        return {
            key: _resolve_templates(item, context)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_templates(item, context) for item in value]
    return value


def _collection_of(payload: dict) -> Optional[list]:
    for key in ("events", "items", "results"):
        items = payload.get(key)
        if isinstance(items, list):
            return items
    return None


class ReadBackVerifier(VerifierPort):
    """Prove plan-step effects by reading the world back."""

    def __init__(
        self,
        *,
        dispatch: ToolDispatchPort,
        memory_search: Optional[Callable] = None,
        tool_levels: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._dispatch = dispatch
        self._memory_search = memory_search
        self._tool_levels = dict(tool_levels or {})

    # ---------------------------------------------------------

    def verify(
        self, step: PlanStep, result: dict
    ) -> VerificationOutcome:
        try:
            return self._verify(step, result)
        except Exception as exc:  # never break the executor
            return VerificationOutcome(
                verdict=Verdict.UNKNOWN,
                observed=f"خطأ داخلي في التحقق: {type(exc).__name__}",
            )

    # ---------------------------------------------------------

    def _verify(
        self, step: PlanStep, result: dict
    ) -> VerificationOutcome:
        if self._is_exempt(step.tool):
            return VerificationOutcome(
                verdict=Verdict.VERIFIED,
                channel="exempt",
                observed="خطوة لا تحتاج قراءة راجعة",
            )

        spec = self._spec_for(step, result)
        if spec is None:
            return VerificationOutcome(
                verdict=Verdict.UNKNOWN,
                observed=(
                    f"لا مواصفة تحقق للأداة {step.tool} — "
                    "لا يمكن إثبات الأثر"
                ),
            )

        context = {
            "step": {"args": step.args, "result": result}
        }
        try:
            args = _resolve_templates(spec.get("args", {}), context)
            params = _resolve_templates(
                spec.get("params", {}), context
            )
        except _Unresolvable as exc:
            return VerificationOutcome(
                verdict=Verdict.UNKNOWN,
                channel=str(
                    spec.get("read_tool")
                    or spec.get("channel")
                    or ""
                ),
                predicate=str(spec.get("predicate", "")),
                observed=f"قالب تحقق لا يمكن حلّه: {exc}",
            )

        channel = str(
            spec.get("read_tool") or spec.get("channel") or ""
        )
        predicate = str(spec.get("predicate", ""))

        payload = self._read_back(spec, args)
        if payload is None:
            return VerificationOutcome(
                verdict=Verdict.UNKNOWN,
                channel=channel,
                predicate=predicate,
                observed="تعذّرت القراءة الراجعة أو أعادت خطأ",
            )

        verdict, observed = self._evaluate(
            predicate, payload, params
        )
        return VerificationOutcome(
            verdict=verdict,
            channel=channel,
            predicate=predicate,
            observed=observed,
        )

    # ---------------------------------------------------------

    def _is_exempt(self, tool: str) -> bool:
        if tool in _EXEMPT_BY_NAME:
            return True
        return self._tool_levels.get(tool) == "read"

    def _spec_for(
        self, step: PlanStep, result: dict
    ) -> Optional[dict]:
        if isinstance(step.verify, dict) and step.verify:
            return step.verify
        if step.tool == "calendar_add":
            if isinstance(result, dict) and result.get("event_id"):
                return _ADD_GET_SPEC
            start = str(step.args.get("start", ""))
            title = step.args.get("title")
            if title and len(start) >= 10:
                day = start[:10]
                return {
                    "read_tool": "calendar_list",
                    "args": {
                        "time_min": f"{day}T00:00:00",
                        "time_max": day,
                        "max_results": 20,
                    },
                    "predicate": "exists_matching",
                    "params": {
                        "match": {
                            "title": "{{step.args.title}}",
                            "start": "{{step.args.start}}",
                        }
                    },
                }
            return None
        if step.tool == "calendar_delete":
            return _DELETE_SPEC
        if step.tool == "remember_fact":
            return _MEMORY_SPEC
        return None

    def _read_back(
        self, spec: dict, args: dict
    ) -> Optional[dict]:
        channel = spec.get("channel")
        if channel is not None:
            if channel != "memory" or self._memory_search is None:
                return None
            query = str(args.get("query", ""))
            if not query:
                return None
            try:
                hits = self._memory_search(query)
            except Exception:
                return None
            if not isinstance(hits, list):
                return None
            return {"ok": True, "items": hits}

        read_tool = spec.get("read_tool")
        if not read_tool:
            return None
        # Defense in depth, on top of plan-accept validation: a
        # read-back may only ever dispatch a read-level tool.
        if (
            self._tool_levels
            and self._tool_levels.get(read_tool) != "read"
        ):
            return None
        try:
            payload = self._dispatch.execute(read_tool, dict(args))
        except Exception:
            return None
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        return payload

    # ---------------------------------------------------------

    def _evaluate(self, predicate: str, payload: dict, params: dict):
        if predicate == "field_equals":
            fields = params.get("fields", {})
            if not isinstance(fields, dict) or not fields:
                return Verdict.UNKNOWN, "مواصفة field_equals بلا حقول"
            for path, expected in fields.items():
                actual = _dig(payload, path)
                if not _values_equal(actual, expected):
                    return (
                        Verdict.FAILED,
                        f"{path}: متوقَّع {expected!r}، "
                        f"مقروء {actual!r}",
                    )
            return (
                Verdict.VERIFIED,
                "طابقت القراءة الراجعة الحقول المتوقعة: "
                + "، ".join(fields.keys()),
            )

        if predicate in ("exists_matching", "absent_matching"):
            match = params.get("match", {})
            items = _collection_of(payload)
            if not isinstance(match, dict) or items is None:
                return (
                    Verdict.UNKNOWN,
                    "مواصفة مطابقة بلا مجموعة مقروءة",
                )
            found = any(
                isinstance(item, dict)
                and all(
                    _values_equal(_dig(item, key), expected)
                    for key, expected in match.items()
                )
                for item in items
            )
            if predicate == "exists_matching":
                if found:
                    return (
                        Verdict.VERIFIED,
                        "وُجد عنصر مطابق في القراءة الراجعة",
                    )
                return (
                    Verdict.FAILED,
                    "لا عنصر مطابق في القراءة الراجعة "
                    f"({len(items)} عنصر مقروء)",
                )
            if found:
                return (
                    Verdict.FAILED,
                    "العنصر ما زال موجودًا في القراءة الراجعة",
                )
            return (
                Verdict.VERIFIED,
                "العنصر غائب كما هو متوقع",
            )

        return Verdict.UNKNOWN, f"محمول تحقق غير معروف: {predicate}"
