from __future__ import annotations

from typing import Any

from core.executor import SafeExecutor
from features.command_execution.application.ports.command_runner import (
    CommandRunnerPort,
)


class ExecutorCommandRunnerAdapter(CommandRunnerPort):
    """
    Adapter satisfying CommandRunnerPort by delegating to the existing,
    already-hardened SafeExecutor.run_command() -- not a reimplementation.

    Why delegate instead of duplicate: every real bug found in this
    codebase's security review came from two parallel implementations
    of the same behavior drifting apart (list_files, tools/system.py's
    weaker run_command copy). SafeExecutor is the hardened authority:
    allowlist, argv parsing without shell, sanitized environment,
    fixed workspace cwd, closed stdin, timeout, bounded output, and
    unified evidence. SafeExecutor.__init__ does no I/O and is cheap.
    """

    def __init__(self, policy):
        self._policy = policy

    def run_command(self, command: str) -> dict[str, Any]:
        executor = SafeExecutor(self._policy)

        return executor.run_command(command)
