from __future__ import annotations

from typing import Any

from core.executor import SafeExecutor


class ExecutorFileVerificationRunnerAdapter:
    """Runner delegating to the hardened SafeExecutor.verify_file."""

    def __init__(self, policy: Any) -> None:
        self._executor = SafeExecutor(policy)

    def run_verification(self, path: str) -> dict:
        return self._executor.verify_file(path)
