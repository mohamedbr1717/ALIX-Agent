"""ExecutionResult (moved verbatim)."""
from __future__ import annotations

from typing import Optional

class ExecutionResult:
    """Moved verbatim from core/executor.py."""

    def __init__(
        self,
        ok: bool,
        action: str,
        message: str = "",
        stdout: str = "",
        stderr: str = "",
        returncode: Optional[int] = None,
        evidence: Optional[dict] = None,
        duration: float = 0.0,
    ):
        self.ok = bool(ok)
        self.action = action
        self.message = message
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.evidence = evidence or {}
        self.duration = round(duration, 3)


    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "action": self.action,
            "message": self.message,
            "stdout": self.stdout[:4000],
            "stderr": self.stderr[:2000],
            "returncode": self.returncode,
            "evidence": self.evidence,
            "duration": self.duration,
        }


