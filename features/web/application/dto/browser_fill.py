from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrowserFillRequest:
    """Request to fill form fields on a page (no submit)."""

    url: str
    fields: dict = field(default_factory=dict)  # {css_selector: value}
