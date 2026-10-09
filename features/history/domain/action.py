"""Action record domain entity (pure, no infrastructure)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionRecord:
    """A single executed tool action, with optional inverse for undo.

    arguments are already redacted (no secrets) when stored.
    inverse: {"tool": str, "arguments": dict} or None if not reversible.
    """

    tool_name: str
    arguments: dict
    timestamp: str  # ISO-8601
    ok: bool
    summary: str = ""
    inverse: dict | None = None
    undone: bool = False

    def is_reversible(self) -> bool:
        return self.ok and not self.undone and self.inverse is not None
