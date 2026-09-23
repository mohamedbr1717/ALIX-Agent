from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifyFileRequest:
    """Request to verify a file's existence and state."""

    path: str
