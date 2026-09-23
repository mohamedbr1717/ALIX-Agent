"""Policy-backed authorization for directory creation."""
from __future__ import annotations

from typing import Any

from features.file_access.application.ports.directory_authorization import (
    DirectoryAuthorizationPort,
)


class PolicyDirectoryAuthorizationAdapter(DirectoryAuthorizationPort):
    """Adapt the existing ALIX Policy to the directory authorization port."""

    def __init__(self, policy: Any):
        self._policy = policy

    def can_create_directory(self, path: str) -> bool:
        # Same gate SafeExecutor.create_directory() itself enforces: a path
        # validate_file_path() rejects is denied before the runner is ever
        # touched. The executor re-validates anyway (defense in depth).
        return self._policy.validate_file_path(path) is not None
