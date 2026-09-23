"""Policy-backed authorization for file listing."""
from __future__ import annotations

from typing import Any

from features.file_access.application.ports.file_listing_authorization import (
    FileListingAuthorizationPort,
)


class PolicyFileListingAuthorizationAdapter(FileListingAuthorizationPort):
    """Allow listing only for paths that resolve inside the workspace."""

    def __init__(self, policy: Any):
        self._policy = policy

    def can_list_files(self, path: str) -> bool:
        try:
            return self._policy.resolve_path(path) is not None
        except Exception:
            # Fail closed on anything resolve_path chokes on.
            return False
