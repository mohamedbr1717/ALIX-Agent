from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FileStoragePort(ABC):
    @abstractmethod
    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
        max_output: int = 4000,
    ) -> dict[str, Any]:
        raise NotImplementedError
