from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchFilesRequest:
    """Request to search for a text pattern inside workspace files."""

    pattern: str
    path: str = "."
    max_matches: int = 20
