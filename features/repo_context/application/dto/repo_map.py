"""DTO for the repo_map tool."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoMapRequest:
    root: str = ""
    max_depth: int = 6
    max_entries: int = 400

    def __post_init__(self):
        try:
            depth = int(self.max_depth)
        except (TypeError, ValueError):
            depth = 6
        try:
            entries = int(self.max_entries)
        except (TypeError, ValueError):
            entries = 400
        object.__setattr__(self, "max_depth", max(1, min(20, depth)))
        object.__setattr__(self, "max_entries", max(10, min(5000, entries)))
        object.__setattr__(self, "root", str(self.root or ""))
