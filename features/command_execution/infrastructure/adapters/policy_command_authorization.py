from __future__ import annotations

from typing import Any

from features.command_execution.application.ports.command_authorization import (
    CommandAuthorizationPort,
)


class PolicyCommandAuthorizationAdapter(CommandAuthorizationPort):
    """Adapt the existing ALIX Policy to the command authorization port."""

    def __init__(self, policy: Any):
        self._policy = policy

    def can_run_command(self, command: str) -> bool:
        # Same gate SafeExecutor.run_command() itself enforces first:
        # policy.command_allowed() on the raw command string. The
        # executor re-checks anyway (plus a second check on the parsed
        # argv), so outcomes are identical with or without this early
        # check -- it just keeps rejected commands from reaching the
        # process layer at all.
        return bool(self._policy.command_allowed(command))
