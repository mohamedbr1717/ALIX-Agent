"""Runner adapter that delegates to the hardened SafeExecutor."""
from __future__ import annotations

from typing import Any

from features.file_access.application.ports.directory_runner import (
    DirectoryRunnerPort,
)


class ExecutorDirectoryRunnerAdapter(DirectoryRunnerPort):
    """Delegate to SafeExecutor.create_directory (workspace containment,
    mkdir with parents=True / exist_ok=True, post-creation verification)."""

    def __init__(self, policy: Any):
        self._policy = policy

    def run_create_directory(self, path: str) -> dict:
        # Deferred import: core.feature_bridge imports this composition at
        # call time, so a module-level core import could cycle.
        from core.executor import SafeExecutor

        return SafeExecutor(self._policy).create_directory(path)
