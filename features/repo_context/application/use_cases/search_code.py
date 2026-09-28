"""search_code use case: authorize root -> backend -> ExecutionResult."""
from __future__ import annotations

import time

from features.repo_context.application.dto.search_code import SearchCodeRequest
from features.repo_context.application.ports.repo_context_authorization import (
    RepoContextAuthorizationPort,
)
from features.repo_context.application.ports.repo_context_backend import (
    RepoContextBackendPort,
)


class SearchCodeUseCase:
    """Application service for the search_code tool (read-only)."""

    def __init__(
        self,
        authorization: RepoContextAuthorizationPort,
        backend: RepoContextBackendPort,
    ):
        self._authorization = authorization
        self._backend = backend

    def execute(self, request: SearchCodeRequest) -> dict:
        started = time.monotonic()
        if not request.query:
            return self._deny(started, "نص البحث فارغ.")
        root = request.root.strip() or self._authorization.default_root()
        if not self._authorization.is_root_allowed(root):
            return self._deny(
                started, f"المسار خارج النطاق المسموح لسياق المستودع: {root}"
            )
        result = self._backend.search_code(
            root, request.query, request.max_results, request.case_sensitive
        )
        if not result.get("ok"):
            return self._deny(started, result.get("error") or "فشل البحث في الكود.")
        return {
            "ok": True,
            "action": "search_code",
            "message": "تم البحث في الكود.",
            "stdout": result.get("text", ""),
            "stderr": "",
            "returncode": 0,
            "evidence": {
                "tool": "search_code",
                "root": root,
                "query": request.query,
                "max_results": request.max_results,
            },
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # Full ExecutionResult shape per SCHEMA_CONTRACT.md.
        return {
            "ok": False,
            "action": "search_code",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
