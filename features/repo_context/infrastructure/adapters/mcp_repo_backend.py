"""Backend adapter: drive the vendored repo-context-mcp server over MCP stdio."""
from __future__ import annotations

import os
from pathlib import Path

from features.repo_context.application.ports.repo_context_backend import (
    RepoContextBackendPort,
)
from features.repo_context.infrastructure.mcp_stdio_client import (
    McpClientError,
    McpStdioClient,
)

SERVER_ENTRY = Path("dist") / "cli.js"


def default_server_dir() -> str:
    """Location of the vendored repo-context-mcp checkout (unmodified)."""
    return os.environ.get(
        "REPO_CONTEXT_MCP_DIR", str(Path.home() / "vendor" / "repo-context-mcp")
    )


class McpRepoBackendAdapter(RepoContextBackendPort):
    """RepoContextBackendPort over a lazily-spawned MCP stdio server."""

    def __init__(self, server_dir=None, timeout=90.0, client=None):
        self._server_dir = str(server_dir or default_server_dir())
        self._timeout = float(timeout)
        self._client = client  # injectable fake for unit tests

    def _get_client(self) -> McpStdioClient:
        if self._client is None:
            entry = str(Path(self._server_dir) / SERVER_ENTRY)
            if not Path(entry).is_file():
                raise McpClientError(
                    "سيرفر repo-context غير مبني: "
                    f"{entry} — نفّذ npm install && npm run build داخل {self._server_dir}"
                )
            self._client = McpStdioClient(
                ["node", entry, "serve"], timeout=self._timeout
            )
        return self._client

    def _call(self, tool: str, arguments: dict) -> dict:
        try:
            result = self._get_client().call_tool(tool, arguments)
        except McpClientError as exc:
            self._client = None  # force a fresh spawn next time
            return {"ok": False, "text": "", "error": str(exc)}
        if result["is_error"]:
            return {"ok": False, "text": "", "error": result["text"] or f"فشل {tool}."}
        return {"ok": True, "text": result["text"], "error": ""}

    def repo_map(self, root: str, max_depth: int, max_entries: int) -> dict:
        return self._call(
            "repo_map",
            {"root": root, "max_depth": max_depth, "max_entries": max_entries},
        )

    def search_code(
        self, root: str, query: str, max_results: int, case_sensitive: bool
    ) -> dict:
        return self._call(
            "search_code",
            {
                "root": root,
                "query": query,
                "max_results": max_results,
                "case_sensitive": case_sensitive,
            },
        )

    def pack_context(
        self, root: str, focus: list, max_tokens: int, max_files: int
    ) -> dict:
        return self._call(
            "pack_context",
            {
                "root": root,
                "focus": focus,
                "max_tokens": max_tokens,
                "max_files": max_files,
            },
        )

    def close(self):
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
