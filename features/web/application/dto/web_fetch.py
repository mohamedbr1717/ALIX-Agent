from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebFetchRequest:
    """Request to fetch the text content of a public URL."""

    url: str
    max_chars: int = 8000
