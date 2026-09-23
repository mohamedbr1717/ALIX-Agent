from __future__ import annotations

from typing import Any

from core.executor import SafeExecutor


class ExecutorSearchRunnerAdapter:
    """Runner delegating to the hardened SafeExecutor.search_files."""

    def __init__(self, policy: Any) -> None:
        self._executor = SafeExecutor(policy)

    def run_search(self, pattern: str, path: str, max_matches: int) -> dict:
        return self._executor.search_files(pattern, path, max_matches)
