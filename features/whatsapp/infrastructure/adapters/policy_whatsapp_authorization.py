"""Policy bridge for WhatsApp authorization (defense in depth).

The agent core already enforces Policy.requires_confirmation (interactive)
and Policy.scheduled_tool_permitted (scheduled mode) before any handler
runs. This adapter makes the use case fail closed if the Policy wiring
ever drifts from the intended level:
  whatsapp_send -> "destructive" (confirm always, never scheduled)
"""
from __future__ import annotations

from typing import Any


class PolicyWhatsAppAuthorizationAdapter:
    def __init__(self, policy: Any) -> None:
        self._policy = policy

    def can_send(self) -> bool:
        return self._policy.tool_permission("whatsapp_send") == "destructive"
