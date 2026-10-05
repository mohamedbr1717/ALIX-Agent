from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserSubmitRequest:
    """Request to perform a final submit/click (booking, purchase, form send)."""

    url: str
    selector: str  # CSS selector of the submit button
    description: str = ""  # human-readable description for confirmation
