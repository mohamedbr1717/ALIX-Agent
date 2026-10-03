"""Policy bridge for phone authorization (defense in depth).

The agent core already enforces Policy.requires_confirmation (interactive)
and Policy.scheduled_tool_permitted (scheduled mode) before any handler
runs. This adapter makes the use case fail closed if the Policy wiring
ever drifts from the intended levels:
  phone_call / send_sms -> "destructive" (confirm always, never scheduled)
  notify                -> "read"        (no confirmation needed)
"""
from __future__ import annotations

from typing import Any


class PolicyPhoneAuthorizationAdapter:
    def __init__(self, policy: Any) -> None:
        self._policy = policy

    def _level(self, tool_name: str) -> Any:
        return self._policy.tool_permission(tool_name)

    def can_call(self, number: str) -> bool:
        return self._level("phone_call") == "destructive"

    def can_text(self, number: str) -> bool:
        return self._level("send_sms") == "destructive"

    def can_notify(self) -> bool:
        return self._level("notify") == "read"
