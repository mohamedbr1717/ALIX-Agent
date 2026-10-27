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

from typing import Callable

from features.planning.application.ports.tool_dispatch import (
    ToolDispatchPort,
)


class CallableToolDispatch(ToolDispatchPort):
    def __init__(self, execute_fn: Callable):
        self._execute_fn = execute_fn

    def execute(self, tool: str, args: dict) -> dict:
        result = self._execute_fn(tool, dict(args))
        if not isinstance(result, dict):
            return {
                "ok": False,
                "error": "نتيجة الأداة غير صالحة.",
            }
        return result
