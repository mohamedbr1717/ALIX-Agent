"""Runner port for read-only system introspection."""
from __future__ import annotations

from abc import ABC, abstractmethod


class SystemRunnerPort(ABC):
    """Executes system introspection via the hardened executor."""

    @abstractmethod
    def run_system_info(self) -> dict:
        """Collect system info; returns the ExecutionResult dict."""

    @abstractmethod
    def run_git_status(self, action: str) -> dict:
        """Run a read-only git action; returns the ExecutionResult dict."""
