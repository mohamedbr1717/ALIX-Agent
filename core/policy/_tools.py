"""Policy _ToolsMixin (private)."""
from __future__ import annotations

from typing import Optional

from domain.rules import confirmation
class _ToolsMixin:
    """Methods moved verbatim."""

    SCHEDULER_CONTROL_TOOLS = frozenset(
        {
            "schedule_task",
            "list_scheduled_tasks",
            "cancel_scheduled_task",
        }
    )


    SCHEDULER_DENIED_TOOLS = frozenset(
        {
            "browse_page",
            "browser_fill",
            "browser_submit",
        }
    )


    def capability_allowed(self, tool_name: str) -> bool:
        """
        Return True only when an explicitly gated capability is enabled.
        Tools without a capability gate remain governed by tool_permissions.
        """
        if not isinstance(tool_name, str):
            return False

        return self.capabilities.get(tool_name, True) is True


    def tool_allowed(self, tool_name: str) -> bool:
        """
        Return True only for explicitly registered policy tools.
        """
        if not isinstance(tool_name, str):
            return False

        if (
            self.scheduled_mode
            and tool_name in self.SCHEDULER_CONTROL_TOOLS
        ):
            return False

        return tool_name in self.tool_permissions


    def tool_permission(self, tool_name: str) -> Optional[str]:
        """
        Return the permission level assigned to a tool.
        """
        if not isinstance(tool_name, str):
            return None

        return self.tool_permissions.get(tool_name)


    def requires_confirmation(
        self,
        tool_name: str,
    ) -> bool:
        """
        Return True when a tool requires explicit user confirmation.
        """

        # Delegated to the pure domain rule (domain/rules/confirmation.py).
        # Policy keeps the *configuration* (tool_permissions); the *decision*
        # (which permission levels demand confirmation) lives in domain.
        return confirmation.requires_confirmation(tool_name, self.tool_permissions)


    def security_summary(self) -> dict:
        return {
            "workspace": str(self.workspace),
            "workspace_isolation": True,
            "symlink_escape_protection": True,
            "sensitive_file_protection": True,
            "command_allowlist": True,
            "blocked_command_list": True,
            "git_restricted": True,
            "python_restricted": True,
            "confirmation_required": True,
            "destructive_confirmation": True,
            "max_command_length": self.max_command_length,
            "max_path_length": self.max_path_length,
            "max_search_pattern_length": self.max_search_pattern_length,
            "max_search_matches": self.max_search_matches,
        }


