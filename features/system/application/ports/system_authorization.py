"""Authorization port for read-only system introspection."""
from __future__ import annotations

from abc import ABC, abstractmethod


class SystemAuthorizationPort(ABC):
    """Policy gates for the system slice (both tools are read-only)."""

    @abstractmethod
    def can_collect_system_info(self) -> bool:
        """True when introspection commands may run under the policy."""

    @abstractmethod
    def can_run_git(self, action: str) -> bool:
        """True when the git action is on the read-only allowlist."""
