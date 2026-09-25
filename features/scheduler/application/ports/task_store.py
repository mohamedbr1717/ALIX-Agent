"""Store port for scheduled tasks."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from features.scheduler.application.dto.scheduler import TaskRecord


class TaskStorePort(ABC):
    """Persistence for scheduled tasks (JSON file in production)."""

    @abstractmethod
    def load_tasks(self) -> List[TaskRecord]:
        """Return all stored tasks (empty list when none)."""

    @abstractmethod
    def save_tasks(self, tasks: List[TaskRecord]) -> None:
        """Atomically persist the full task list."""
