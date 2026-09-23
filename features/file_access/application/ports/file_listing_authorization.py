"""Authorization port for file listing."""
from __future__ import annotations

from abc import ABC, abstractmethod


class FileListingAuthorizationPort(ABC):
    """Decides whether files may be listed at the given path."""

    @abstractmethod
    def can_list_files(self, path: str) -> bool:
        """True when listing files at `path` is allowed."""
