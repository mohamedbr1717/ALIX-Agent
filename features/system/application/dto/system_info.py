"""DTO for the system_info use case."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemInfoRequest:
    """system_info takes no arguments."""
