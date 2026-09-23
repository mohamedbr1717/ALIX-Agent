"""Policy-backed authorization for the system slice."""
from __future__ import annotations

from typing import Any

from features.system.application.ports.system_authorization import (
    SystemAuthorizationPort,
)


class PolicySystemAuthorizationAdapter(SystemAuthorizationPort):
    """Adapt the existing ALIX Policy to the system authorization port."""

    def __init__(self, policy: Any):
        self._policy = policy

    def can_collect_system_info(self) -> bool:
        # Same per-command gate SafeExecutor.system_info() enforces (it
        # skips commands policy.command_allowed rejects). Denying here
        # only when *no* introspection command is allowed keeps a
        # fully-locked-down policy from reaching the runner at all.
        return bool(
            self._policy.command_allowed("uname -a")
            or self._policy.command_allowed("free -h")
        )

    def can_run_git(self, action: str) -> bool:
        # Same read-only allowlist SafeExecutor.git_read_only() enforces.
        return action in self._policy.allowed_git_commands
