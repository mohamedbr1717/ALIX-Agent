"""History DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LogActionRequest:
    tool_name: str
    arguments: dict
    ok: bool
    summary: str = ""
    inverse: dict | None = None


@dataclass(frozen=True)
class ListHistoryRequest:
    limit: int = 10


@dataclass(frozen=True)
class HistoryResult:
    ok: bool
    message: str
    actions: list = field(default_factory=list)
    undone_action: dict | None = None
