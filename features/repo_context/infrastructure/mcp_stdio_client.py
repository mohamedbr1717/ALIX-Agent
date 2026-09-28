"""Minimal MCP stdio client (JSON-RPC, newline-delimited).

Speaks just enough of the Model Context Protocol to drive the vendored
repo-context-mcp server: initialize, notifications/initialized, tools/call.
No external dependencies; the server keeps stdout protocol-clean.
"""
from __future__ import annotations

import json
import select
import subprocess
import threading
import time

PROTOCOL_VERSION = "2024-11-05"


class McpClientError(Exception):
    """Raised when the MCP server cannot be reached or misbehaves."""


class McpStdioClient:
    """Lifecycle-managed stdio MCP client for one server process."""

    def __init__(self, command, cwd=None, timeout=90.0, env=None):
        self._command = list(command)
        self._cwd = cwd
        self._timeout = float(timeout)
        self._env = env
        self._proc = None
        self._next_id = 0
        # RLock: _request() holds the lock while _ensure_started() may
        # handshake (which itself sends requests).
        self._lock = threading.RLock()

    # ----------------------------------------------------------
    # lifecycle
    # ----------------------------------------------------------
    def _ensure_started(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        self._spawn()

    def _spawn(self):
        try:
            proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self._cwd,
                env=self._env,
            )
        except OSError as exc:
            raise McpClientError(f"تعذر تشغيل سيرفر repo-context: {exc}")
        self._proc = proc
        self._next_id = 0
        try:
            self._handshake()
        except Exception:
            self._kill()
            raise

    def _handshake(self):
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "alix-agent", "version": "1.0"},
        })
        # Notification: no id, no response expected.
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def close(self):
        with self._lock:
            self._kill()

    def _kill(self):
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ----------------------------------------------------------
    # protocol
    # ----------------------------------------------------------
    def _request(self, method, params=None):
        with self._lock:
            self._ensure_started()
            self._next_id += 1
            rid = self._next_id
            message = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params:
                message["params"] = params
            self._send(message)
            return self._read_response(rid)

    def _send(self, message):
        data = (json.dumps(message) + "\n").encode("utf-8")
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpClientError(f"انقطع الاتصال بسيرفر repo-context: {exc}")

    def _read_response(self, rid):
        deadline = time.monotonic() + self._timeout
        stdout = self._proc.stdout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpClientError("انتهت المهلة بانتظار رد سيرفر repo-context.")
            ready, _, _ = select.select([stdout], [], [], remaining)
            if not ready:
                raise McpClientError("انتهت المهلة بانتظار رد سيرفر repo-context.")
            chunk = stdout.readline()
            if not chunk:
                raise McpClientError("أغلق سيرفر repo-context الاتصال فجأة.")
            try:
                message = json.loads(chunk.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue  # skip non-JSON noise lines
            if not isinstance(message, dict) or message.get("id") != rid:
                continue  # notifications or stray messages
            if "error" in message:
                err = message["error"]
                detail = err.get("message", err) if isinstance(err, dict) else err
                raise McpClientError(f"خطأ من سيرفر repo-context: {detail}")
            result = message.get("result", {})
            return result if isinstance(result, dict) else {}

    # ----------------------------------------------------------
    # tools
    # ----------------------------------------------------------
    def call_tool(self, name, arguments):
        """Call a tool; returns {"text": str, "is_error": bool}."""
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        content = result.get("content") or []
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return {"text": "\n".join(texts), "is_error": bool(result.get("isError"))}
