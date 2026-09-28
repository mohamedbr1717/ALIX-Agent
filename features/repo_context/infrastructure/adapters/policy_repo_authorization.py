"""Authorization adapter: root allowlist derived from Policy + env."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from features.repo_context.application.ports.repo_context_authorization import (
    RepoContextAuthorizationPort,
)
from features.repo_context.domain.root_policy import is_root_allowed, normalize_root


class PolicyRepoAuthorizationAdapter(RepoContextAuthorizationPort):
    """Allowlist = policy base_dir + policy workspace + ALIX_REPO_CONTEXT_ROOTS.

    Extra roots come from the colon-separated ALIX_REPO_CONTEXT_ROOTS env var.
    Everything else fails closed.
    """

    def __init__(self, policy: Any):
        self._policy = policy
        self._allowed = self._build_allowlist(policy)

    @staticmethod
    def _build_allowlist(policy: Any) -> list:
        roots: list = []
        for attr in ("base_dir", "workspace"):
            value = getattr(policy, attr, None)
            if value:
                roots.append(str(value))
        extra = os.environ.get("ALIX_REPO_CONTEXT_ROOTS", "")
        for part in extra.split(":"):
            part = part.strip()
            if part:
                roots.append(part)
        deduped: list = []
        for root in roots:
            normalized = normalize_root(root)
            if normalized not in deduped:
                deduped.append(normalized)
        return deduped

    @property
    def allowed_roots(self) -> list:
        return list(self._allowed)

    def default_root(self) -> str:
        base = getattr(self._policy, "base_dir", None)
        if base:
            return normalize_root(str(base))
        return normalize_root(str(Path.cwd()))

    def is_root_allowed(self, root: str) -> bool:
        if not root or not str(root).strip():
            return False
        return is_root_allowed(root, self._allowed)
