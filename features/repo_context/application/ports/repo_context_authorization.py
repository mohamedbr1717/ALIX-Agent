"""Authorization port for repo-context roots."""
from __future__ import annotations

from abc import ABC, abstractmethod


class RepoContextAuthorizationPort(ABC):
    """Decides which repository roots the agent may inspect."""

    @abstractmethod
    def default_root(self) -> str:
        """Root used when the tool call omits one (the ALIX repo itself)."""

    @abstractmethod
    def is_root_allowed(self, root: str) -> bool:
        """Fail-closed allowlist check for a requested root."""
