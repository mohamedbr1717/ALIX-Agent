from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchRequest:
    """Request to search the web."""

    query: str
    max_results: int = 5
