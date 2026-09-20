from __future__ import annotations

from typing import Any

from core.executor import SafeExecutor
from features.file_access.application.dto.read_file import (
    DEFAULT_MAX_OUTPUT,
    MIN_MAX_OUTPUT,
)
from features.file_access.application.ports.file_storage import FileStoragePort


class WorkspaceFileStorageAdapter(FileStoragePort):
    """
    Adapter satisfying FileStoragePort by delegating to the existing,
    already-hardened SafeExecutor.read_file() -- not a reimplementation.

    Why delegate instead of duplicate:
    every real bug found in this codebase's security review came from
    two parallel implementations of the same behavior drifting apart
    (list_files, the run_python capability gate, the "\n" join bug).
    The adapter's job is to satisfy the port contract; how it does
    that is an implementation detail, and reusing proven, tested
    infrastructure code is the correct way to do it.
    """

    def __init__(self, policy, max_output: int = DEFAULT_MAX_OUTPUT):
        self._policy = policy
        self._default_max_output = max(MIN_MAX_OUTPUT, int(max_output))

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
        max_output: int = 4000,
    ) -> dict[str, Any]:
        # SafeExecutor.max_output is fixed per-instance, but this
        # port's contract takes max_output per call -- construct a
        # scoped executor for this call. SafeExecutor.__init__ does
        # no I/O and is cheap (no sandbox is touched here; that only
        # happens inside run_python()).
        executor = SafeExecutor(
            self._policy,
            max_output=max(1, int(max_output or self._default_max_output)),
        )

        return executor.read_file(
            path,
            start_line=start_line,
            end_line=end_line,
        )

    def write_file(
        self,
        path: str,
        content: str,
    ) -> dict[str, Any]:
        # Same delegation philosophy as read_file above: SafeExecutor
        # is the hardened, tested authority for writes -- path
        # confinement, .alix-backup before overwrite, and independent
        # post-write verification. Duplicating that logic here is how
        # the old parallel implementations drifted apart; the
        # adapter's job is to satisfy the port contract, nothing more.
        # SafeExecutor.__init__ does no I/O and is cheap.
        executor = SafeExecutor(self._policy)

        return executor.write_file(path, content)
