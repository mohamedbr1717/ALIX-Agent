"""Policy _ScheduledMixin (private)."""
from __future__ import annotations

class _ScheduledMixin:
    """Methods moved verbatim."""

    def scheduled_tool_permitted(
        self,
        tool_name: str,
    ) -> bool:
        """
        Scheduled-mode gate: pre-authorized ceiling, never
        destructive. Called by the agent instead of the
        interactive confirmation when scheduled_mode is on.
        """
        if not self.scheduled_mode:
            return True

        # Explicit denylist: these tools never run in scheduled mode,
        # regardless of their permission level or the ceiling.
        if tool_name in self.SCHEDULER_DENIED_TOOLS:
            return False

        level = self.tool_permissions.get(tool_name)
        order = self.permission_levels

        if level not in order:
            return False

        if level == "destructive":
            # Fail-closed: destructive tools never run unattended.
            return False

        allowed = self.scheduled_allow

        if allowed not in order:
            allowed = "read"

        return order[level] <= order[allowed]


