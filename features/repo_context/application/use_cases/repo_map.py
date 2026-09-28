"""repo_map use case: authorize root -> backend -> ExecutionResult."""
from __future__ import annotations

import time

from features.repo_context.application.dto.repo_map import RepoMapRequest
from features.repo_context.application.ports.repo_context_authorization import (
    RepoContextAuthorizationPort,
)
from features.repo_context.application.ports.repo_context_backend import (
    RepoContextBackendPort,
)


class RepoMapUseCase:
    """Application service for the repo_map tool (read-only)."""

    def __init__(
        self,
        authorization: RepoContextAuthorizationPort,
        backend: RepoContextBackendPort,
    ):
        self._authorization = authorization
        self._backend = backend

    def execute(self, request: RepoMapRequest) -> dict:
        started = time.monotonic()
        root = request.root.strip() or self._authorization.default_root()
        if not self._authorization.is_root_allowed(root):
            return self._deny(
                started, f"المسار خارج النطاق المسموح لسياق المستودع: {root}"
            )
        result = self._backend.repo_map(root, request.max_depth, request.max_entries)
        if not result.get("ok"):
            return self._deny(started, result.get("error") or "فشل بناء خريطة المستودع.")
        return {
            "ok": True,
            "action": "repo_map",
            "message": "تم بناء خريطة المستودع.",
            "stdout": result.get("text", ""),
            "stderr": "",
            "returncode": 0,
            "evidence": {
                "tool": "repo_map",
                "root": root,
                "max_depth": request.max_depth,
                "max_entries": request.max_entries,
            },
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # Full ExecutionResult shape per SCHEMA_CONTRACT.md.
        return {
            "ok": False,
            "action": "repo_map",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
