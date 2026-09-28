"""Backend port: repo-context operations served by the external MCP server."""
from __future__ import annotations

from abc import ABC, abstractmethod


class RepoContextBackendPort(ABC):
    """Speaks to repo-context-mcp (MCP over stdio) and returns raw results.

    Every method returns {"ok": bool, "text": str, "error": str}.
    """

    @abstractmethod
    def repo_map(self, root: str, max_depth: int, max_entries: int) -> dict:
        """Build a lightweight repo map; text is markdown."""

    @abstractmethod
    def search_code(
        self, root: str, query: str, max_results: int, case_sensitive: bool
    ) -> dict:
        """Substring search; text lists path:line hits."""

    @abstractmethod
    def pack_context(
        self, root: str, focus: list, max_tokens: int, max_files: int
    ) -> dict:
        """Token-budgeted markdown pack; text is the markdown bundle."""
