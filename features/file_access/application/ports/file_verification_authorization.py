from __future__ import annotations

from typing import Protocol


class FileVerificationAuthorization(Protocol):
    """Decides whether a path may be verified (deny-before-runner)."""

    def can_verify(self, path: str) -> bool: ...
