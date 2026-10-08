"""SafeExecutor facade (public API unchanged)."""
from __future__ import annotations

import subprocess  # re-exported: tests patch "core.executor.subprocess.*"
import time
from typing import Optional

from core.policy import Policy
from core.sandbox import ProotSandbox, SandboxUnavailable
from .result import ExecutionResult
from ._process import _ProcessMixin
from ._files import _FilesMixin
from ._terminal import _TerminalMixin

class SafeExecutor(
    _ProcessMixin,
    _FilesMixin,
    _TerminalMixin,
):
    """Safe execution engine facade."""

    def __init__(
        self,
        policy: Optional[Policy] = None,
        command_timeout: int = 30,
        python_timeout: int = 30,
        max_output: int = 4000,
        sandbox_cls: Optional[type] = None,
    ):
        self.policy = policy or Policy()

        self.command_timeout = max(1, int(command_timeout))
        self.python_timeout = max(1, int(python_timeout))
        self.max_output = max(500, int(max_output))

        # SECURITY: real OS-level isolation for run_python (see
        # core/sandbox.py). Injectable so tests can substitute a
        # lightweight fake without requiring `proot` to be installed
        # on the machine running the test suite -- the real
        # ProotSandbox class itself is covered separately in
        # test_sandbox.py.
        self._sandbox_cls = sandbox_cls or ProotSandbox


    def _base_result(
        self,
        action: str,
        started: float,
        ok: bool,
        message: str = "",
        **kwargs,
    ) -> ExecutionResult:
        return ExecutionResult(
            ok=ok,
            action=action,
            message=message,
            duration=time.monotonic() - started,
            **kwargs,
        )


__all__ = ["SafeExecutor", "ExecutionResult", "ProotSandbox", "SandboxUnavailable", "subprocess"]
