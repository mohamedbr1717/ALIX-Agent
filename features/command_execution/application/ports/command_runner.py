from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CommandRunnerPort(ABC):
    @abstractmethod
    def run_command(self, command: str) -> dict[str, Any]:
        raise NotImplementedError
