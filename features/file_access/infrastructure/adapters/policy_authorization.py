from __future__ import annotations

from typing import Any

from features.file_access.application.ports.authorization import (
    AuthorizationPort,
)


class PolicyAuthorizationAdapter(AuthorizationPort):
    """Adapt the existing ALIX Policy to the file-access authorization port."""

    def __init__(self, policy: Any):
        self._policy = policy

    def can_read_file(self, path: str) -> bool:
        return self._policy.validate_file_path(path) is not None

    def can_write_file(self, path: str) -> bool:
        # Same gate SafeExecutor.write_file() itself enforces: a path
        # validate_file_path() rejects is denied before storage is
        # ever touched. The executor re-validates anyway (defense in
        # depth), so outcomes are identical with or without this
        # early check -- the check just keeps unauthorized writes
        # from reaching the filesystem layer at all.
        return self._policy.validate_file_path(path) is not None

    def can_delete_file(self, path: str) -> bool:
        # Same gate SafeExecutor.delete_file() itself enforces: a path
        # validate_file_path() rejects is denied before storage is
        # ever touched. The executor re-validates anyway (defense in
        # depth), so outcomes are identical with or without this
        # early check.
        return self._policy.validate_file_path(path) is not None
