"""DTO for the list_files use case."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListFilesRequest:
    """Input for listing files inside the workspace."""

    path: str = "."
    all: bool = False
