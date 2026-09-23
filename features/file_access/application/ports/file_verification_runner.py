from __future__ import annotations

from typing import Protocol


class FileVerificationRunner(Protocol):
    """Verifies a file and returns the result dict."""

    def run_verification(self, path: str) -> dict: ...
