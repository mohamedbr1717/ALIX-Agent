"""Runner port for directory creation."""
from __future__ import annotations

from abc import ABC, abstractmethod


class DirectoryRunnerPort(ABC):
    """Executes the actual directory creation (infrastructure)."""

    @abstractmethod
    def run_create_directory(self, path: str) -> dict:
        """Create the directory; returns the ExecutionResult dict."""
