"""Action store port."""

from __future__ import annotations

from typing import Protocol


class ActionStore(Protocol):
    """Append-only store for action records."""

    def append(self, record: dict) -> None:
        ...

    def list_recent(self, limit: int) -> list[dict]:
        ...

    def mark_undone(self, index: int) -> bool:
        """Mark action at index as undone. Returns True if found."""
        ...
