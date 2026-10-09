"""Calendar gateway port (implemented by infrastructure adapters)."""

from __future__ import annotations

from typing import Protocol


class CalendarGateway(Protocol):
    """Port for calendar provider operations."""

    def list_events(
        self, time_min: str, time_max: str, max_results: int
    ) -> dict:
        """Return {"ok": bool, "events": [...], "error": ...}."""
        ...

    def add_event(self, event: dict) -> dict:
        """Return {"ok": bool, "event_id": ..., "error": ...}."""
        ...

    def delete_event(self, event_id: str) -> dict:
        """Return {"ok": bool, "error": ...}."""
        ...
