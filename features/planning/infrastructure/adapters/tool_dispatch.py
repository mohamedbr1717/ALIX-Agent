"""Callable dispatch adapter: the ToolDispatchPort's one
production implementation.

Wraps an injected ``execute(tool, args) -> dict`` callable —
wired in core/feature_bridge.py to the agent's existing
``execute_tool`` — so plan steps travel the exact same gated
path as model-issued tool calls (spec §4.4). This class adds no
gates of its own and must never grow any: one dispatch entrance,
one Policy path.
"""
from __future__ import annotations

import inspect
from typing import Callable

from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)


def _accepts_consent(fn: Callable) -> bool:
    """True when ``fn`` can take a third positional argument.

    Probed ONCE from the signature — never by try/except around
    the call, which could mask a genuine error raised inside the
    pipeline as a wiring mismatch.
    """
    try:
        params = list(
            inspect.signature(fn).parameters.values()
        )
    except (TypeError, ValueError):
        return False
    if any(
        p.kind is inspect.Parameter.VAR_POSITIONAL
        for p in params
    ):
        return True
    positional = [
        p
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    return len(positional) >= 3


class CallableToolDispatch(ToolDispatchPort):
    def __init__(self, execute_fn: Callable):
        self._execute_fn = execute_fn
        self._accepts_consent = _accepts_consent(execute_fn)

    def execute(
        self, tool: str, args: dict, consent_digest: str = None
    ) -> dict:
        # Decision 7: the consent digest rides the SAME single
        # dispatch entrance as a call-level parameter — it never
        # becomes a tool argument, and an absent digest keeps the
        # exact legacy two-argument call so every existing wiring
        # and fake is untouched. A wiring whose callable cannot
        # carry the digest (a pipeline without the consent
        # channel) also gets the legacy call: the digest is
        # dropped and the step faces the pipeline's own card —
        # degradation is always toward asking, never toward
        # executing.
        if consent_digest is None or not self._accepts_consent:
            result = self._execute_fn(tool, dict(args))
        else:
            result = self._execute_fn(
                tool, dict(args), consent_digest
            )
        if not isinstance(result, dict):
            return {
                "ok": False,
                "error": "نتيجة الأداة غير صالحة.",
            }
        return result
