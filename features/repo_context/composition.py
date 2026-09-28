"""Composition root for the repo_context feature (read-only repo introspection).

Drives the vendored repo-context-mcp server (MCP over stdio, unmodified)
through a lazily-spawned node process. One backend instance is shared by the
three controllers so a single server process serves all three tools.
"""
from __future__ import annotations

from features.repo_context.application.use_cases.pack_context import PackContextUseCase
from features.repo_context.application.use_cases.repo_map import RepoMapUseCase
from features.repo_context.application.use_cases.search_code import SearchCodeUseCase
from features.repo_context.infrastructure.adapters.mcp_repo_backend import (
    McpRepoBackendAdapter,
    default_server_dir,
)
from features.repo_context.infrastructure.adapters.policy_repo_authorization import (
    PolicyRepoAuthorizationAdapter,
)
from features.repo_context.interfaces.controllers.pack_context_controller import (
    PackContextController,
)
from features.repo_context.interfaces.controllers.repo_map_controller import (
    RepoMapController,
)
from features.repo_context.interfaces.controllers.search_code_controller import (
    SearchCodeController,
)

_shared_backends: dict = {}


def _shared_backend() -> McpRepoBackendAdapter:
    key = default_server_dir()
    backend = _shared_backends.get(key)
    if backend is None:
        backend = McpRepoBackendAdapter(server_dir=key)
        _shared_backends[key] = backend
    return backend


def build_repo_map_controller(policy):
    """Build the repo_map controller with its default adapters."""
    authorization = PolicyRepoAuthorizationAdapter(policy)
    use_case = RepoMapUseCase(authorization, _shared_backend())
    return RepoMapController(use_case)


def build_search_code_controller(policy):
    """Build the search_code controller with its default adapters."""
    authorization = PolicyRepoAuthorizationAdapter(policy)
    use_case = SearchCodeUseCase(authorization, _shared_backend())
    return SearchCodeController(use_case)


def build_pack_context_controller(policy):
    """Build the pack_context controller with its default adapters."""
    authorization = PolicyRepoAuthorizationAdapter(policy)
    use_case = PackContextUseCase(authorization, _shared_backend())
    return PackContextController(use_case)
