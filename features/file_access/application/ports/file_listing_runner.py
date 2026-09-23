"""Runner port for file listing."""
from __future__ import annotations

from abc import ABC, abstractmethod


class FileListingRunnerPort(ABC):
    """Executes the actual file listing (infrastructure)."""

    @abstractmethod
    def run_list_files(self, path: str, all: bool) -> dict:
        """List files; returns the ExecutionResult dict."""
