"""Executor port: runs one scheduled task's prompt, returns text."""
from __future__ import annotations

from abc import ABC, abstractmethod


class TaskExecutorPort(ABC):
    """Executes a task prompt under scheduled-mode policy."""

    @abstractmethod
    def execute_task(
        self,
        prompt: str,
        allow: str,
    ) -> str:
        """Run the prompt; return the final text (or error text)."""
