"""Tool dispatch port: the executor's ONLY way to run a tool.

The single production adapter wraps the agent's existing
``execute_tool`` (wired in core/feature_bridge.py), so every plan
step passes the same registry gate, canary, Policy checks,
argument validation and confirmation pipeline as a model-issued
call (spec §4.4). There is deliberately no other dispatch method
anywhere in this slice.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ToolDispatchPort(ABC):
    """Executes one tool call through the existing Policy path."""

    @abstractmethod
    def execute(self, tool: str, args: dict) -> dict:
        """Run ``tool`` with ``args``; returns the unified result
        contract dict (ok, action, message, stdout, stderr,
        returncode, evidence, duration — see SCHEMA_CONTRACT.md).
        """
