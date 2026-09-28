"""pack_context use case: authorize root -> backend -> ExecutionResult."""
from __future__ import annotations

import re
import time

from features.repo_context.application.dto.pack_context import PackContextRequest
from features.repo_context.application.ports.repo_context_authorization import (
    RepoContextAuthorizationPort,
)
from features.repo_context.application.ports.repo_context_backend import (
    RepoContextBackendPort,
)

_TOKENS_RE = re.compile(r"~(\d+)\s+tokens")


def parse_packed_tokens(markdown: str) -> int | None:
    """Best-effort parse of the '~N tokens' header the server emits."""
    match = _TOKENS_RE.search(markdown or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


class PackContextUseCase:
    """Application service for the pack_context tool (read-only)."""

    def __init__(
        self,
        authorization: RepoContextAuthorizationPort,
        backend: RepoContextBackendPort,
    ):
        self._authorization = authorization
        self._backend = backend

    def execute(self, request: PackContextRequest) -> dict:
        started = time.monotonic()
        root = request.root.strip() or self._authorization.default_root()
        if not self._authorization.is_root_allowed(root):
            return self._deny(
                started, f"المسار خارج النطاق المسموح لسياق المستودع: {root}"
            )
        result = self._backend.pack_context(
            root, request.focus, request.max_tokens, request.max_files
        )
        if not result.get("ok"):
            return self._deny(started, result.get("error") or "فشل تجميع سياق المستودع.")
        text = result.get("text", "")
        evidence = {
            "tool": "pack_context",
            "root": root,
            "focus": request.focus,
            "max_tokens": request.max_tokens,
            "max_files": request.max_files,
        }
        packed_tokens = parse_packed_tokens(text)
        if packed_tokens is not None:
            evidence["packed_tokens"] = packed_tokens
            evidence["within_budget"] = packed_tokens <= request.max_tokens
        return {
            "ok": True,
            "action": "pack_context",
            "message": "تم تجميع سياق المستودع ضمن الميزانية.",
            "stdout": text,
            "stderr": "",
            "returncode": 0,
            "evidence": evidence,
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        # Full ExecutionResult shape per SCHEMA_CONTRACT.md.
        return {
            "ok": False,
            "action": "pack_context",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
