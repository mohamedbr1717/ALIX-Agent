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
