"""Policy bridge for Meta publishing authorization (defense in depth).

The agent core already enforces Policy.requires_confirmation (interactive)
and the scheduled-mode rules before any handler runs. This adapter makes
each use case fail closed if the Policy wiring ever drifts from the
intended level for its tool:
  facebook_post_text / facebook_post_photo -> "destructive"
(confirm every time interactively; in scheduled mode the core suspends
the call and escalates via the 180s Telegram approval card — it never
runs unattended.)
"""
from __future__ import annotations

from typing import Any


class PolicyMetaAuthorizationAdapter:
    def __init__(self, policy: Any, tool_name: str) -> None:
        self._policy = policy
        self._tool_name = tool_name

    def can_publish(self) -> bool:
        return self._policy.tool_permission(self._tool_name) == "destructive"
