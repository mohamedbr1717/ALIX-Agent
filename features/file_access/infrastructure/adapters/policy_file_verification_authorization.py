from __future__ import annotations

from typing import Any


class PolicyFileVerificationAuthorizationAdapter:
    """Authorization via Policy.validate_file_path (workspace containment)."""

    def __init__(self, policy: Any) -> None:
        self._policy = policy

    def can_verify(self, path: str) -> bool:
        return self._policy.validate_file_path(path) is not None
