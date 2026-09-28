"""DTO for the search_code tool."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchCodeRequest:
    query: str = ""
    root: str = ""
    max_results: int = 50
    case_sensitive: bool = False

    def __post_init__(self):
        query = str(self.query or "").strip()[:200]
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "root", str(self.root or ""))
        try:
            limit = int(self.max_results)
        except (TypeError, ValueError):
            limit = 50
        object.__setattr__(self, "max_results", max(1, min(500, limit)))
        object.__setattr__(self, "case_sensitive", bool(self.case_sensitive))
