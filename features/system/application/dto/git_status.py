"""DTO for the git_status use case."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitStatusRequest:
    """Read-only git action; defaults to 'status' like the old dispatch."""

    action: str = "status"
