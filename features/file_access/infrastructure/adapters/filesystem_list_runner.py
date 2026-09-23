"""Runner adapter that delegates to the canonical FileSystemTools."""
from __future__ import annotations

from typing import Any

from features.file_access.application.ports.file_listing_runner import (
    FileListingRunnerPort,
)


class FileSystemToolsListRunnerAdapter(FileListingRunnerPort):
    """Delegate to FileSystemTools.list_files.

    SafeExecutor exposes no equivalent operation, so the hardened
    FileSystemTools implementation remains the execution authority here
    (same delegation pattern as the executor-backed adapters).
    """

    def __init__(self, policy: Any):
        self._policy = policy

    def run_list_files(self, path: str, all: bool) -> dict:
        # Deferred import: core.feature_bridge imports this composition at
        # call time, so a module-level tools import could cycle.
        from tools.filesystem import FileSystemTools

        return FileSystemTools(self._policy).list_files(path, all=all)
