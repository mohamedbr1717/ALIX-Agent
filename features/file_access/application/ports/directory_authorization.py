"""Authorization port for directory creation."""
from __future__ import annotations

from abc import ABC, abstractmethod


class DirectoryAuthorizationPort(ABC):
    """Decides whether a directory may be created at the given path."""

    @abstractmethod
    def can_create_directory(self, path: str) -> bool:
        """True when creating a directory at `path` is allowed."""
