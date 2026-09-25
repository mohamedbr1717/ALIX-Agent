"""Authorization port for the scheduler slice."""
from __future__ import annotations

from abc import ABC, abstractmethod


class SchedulerAuthorizationPort(ABC):
    """Policy gates for scheduling control-plane actions."""

    @abstractmethod
    def can_schedule(self) -> bool:
        """True when creating a scheduled task is allowed."""

    @abstractmethod
    def can_cancel(self) -> bool:
        """True when cancelling a scheduled task is allowed."""

    @abstractmethod
    def can_list(self) -> bool:
        """True when listing scheduled tasks is allowed."""
