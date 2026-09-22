from __future__ import annotations

from abc import ABC, abstractmethod


class CommandAuthorizationPort(ABC):
    @abstractmethod
    def can_run_command(self, command: str) -> bool:
        raise NotImplementedError
