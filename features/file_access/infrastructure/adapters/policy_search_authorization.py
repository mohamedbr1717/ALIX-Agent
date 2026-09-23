from __future__ import annotations

from typing import Any


class PolicySearchAuthorizationAdapter:
    """Authorization via Policy gates (pattern + path)."""

    def __init__(self, policy: Any) -> None:
        self._policy = policy

    def can_search_files(self, pattern: str, path: str) -> bool:
        if not self._policy.validate_search_pattern(pattern):
            return False
        return self._policy.validate_file_path(path) is not None
