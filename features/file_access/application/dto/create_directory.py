"""DTO for the create_directory use case."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateDirectoryRequest:
    """Validated input for creating a directory inside the workspace."""

    path: str
