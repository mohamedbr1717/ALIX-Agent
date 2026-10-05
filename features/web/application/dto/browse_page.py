from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowsePageRequest:
    """Request to load a page in headless Chromium and extract text."""

    url: str
    max_chars: int = 8000
