"""Pure domain rule: the confirmation gate for ALIX.

Framework-free: no Policy, no I/O, no side effects. The enterprise rule
"which tools require explicit user confirmation before execution" as a
pure function.

Policy keeps the *configuration* (tool_permissions: tool name ->
permission level); the *decision* (which levels demand confirmation)
lives here.
"""

from __future__ import annotations

from typing import Mapping

#: Permission levels that require explicit user confirmation.
CONFIRMING_PERMISSIONS = frozenset({"write", "execute", "destructive"})


def requires_confirmation(
    tool_name: str,
    tool_permissions: Mapping[str, str],
) -> bool:
    """True when the named tool requires explicit user confirmation."""
    if not isinstance(tool_name, str):
        return False

    return tool_permissions.get(tool_name) in CONFIRMING_PERMISSIONS
