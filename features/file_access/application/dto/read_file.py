from __future__ import annotations

from dataclasses import dataclass


MIN_MAX_OUTPUT = 500
DEFAULT_MAX_OUTPUT = 4000


@dataclass(frozen=True)
class ReadFileRequest:
    path: str
    start_line: int = 1
    end_line: int | None = None
    max_output: int = DEFAULT_MAX_OUTPUT

    def normalized_max_output(self) -> int:
        return max(MIN_MAX_OUTPUT, int(self.max_output))
