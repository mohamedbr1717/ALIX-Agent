#!/usr/bin/env python3
"""Tests: MCP threat model — destructive tools hidden/denied by default,
opt-in via ALIX_MCP_ALLOW_DESTRUCTIVE=1.

Run from the repo root: python3 -m pytest test_mcp_threat_model.py -q
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import mcp_server
from mcp_server import ALIXMCPServer


def make_server(env: dict | None = None):
    env = env or {}
    with mock.patch.dict(os.environ, env, clear=False):
        # Ensure the flag is absent unless explicitly set.
        if "ALIX_MCP_ALLOW_DESTRUCTIVE" not in env:
            os.environ.pop("ALIX_MCP_ALLOW_DESTRUCTIVE", None)
        with mock.patch.object(mcp_server, "Memory",
                               return_value=mock.Mock()):
            return ALIXMCPServer()


def list_names(server):
    res = server.handle_request({"jsonrpc": "2.0", "id": 1,
                                 "method": "tools/list", "params": {}})
    return [t["name"] for t in res["result"]["tools"]]


def call(server, name, arguments, msg_id=1):
    return server.handle_request({
        "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })


def result_text(res):
    return res["result"]["content"][0]["text"]


class TestMCPThreatModel(unittest.TestCase):
    def test_destructive_hidden_from_list_by_default(self):
        s = make_server()
        names = list_names(s)
        for destructive in ("delete_file", "run_command", "run_python",
                            "write_file", "create_directory"):
            self.assertNotIn(destructive, names)
        # Safe tools still listed.
        self.assertIn("read_file", names)

    def test_destructive_denied_in_call_by_default(self):
        s = make_server()
        s.registry.execute = mock.Mock()
        res = call(s, "delete_file",
                   {"path": "x.txt", "confirmed": True})
        # Even WITH confirmed:true, denied — the client is not trusted.
        s.registry.execute.assert_not_called()
        self.assertIn("محظورة", result_text(res))

    def test_opt_in_lists_destructive(self):
        s = make_server({"ALIX_MCP_ALLOW_DESTRUCTIVE": "1"})
        names = list_names(s)
        self.assertIn("delete_file", names)

    def test_opt_in_still_requires_confirmed(self):
        s = make_server({"ALIX_MCP_ALLOW_DESTRUCTIVE": "1"})
        s.registry.execute = mock.Mock(
            return_value={"ok": True, "message": "done"})
        # Without confirmed -> denied.
        res = call(s, "delete_file", {"path": "x.txt"})
        s.registry.execute.assert_not_called()
        self.assertIn("تأكيد", result_text(res))
        # With confirmed -> proceeds.
        call(s, "delete_file", {"path": "x.txt", "confirmed": True})
        s.registry.execute.assert_called_once_with(
            "delete_file", {"path": "x.txt"})

    def test_safe_tools_unaffected_by_default(self):
        s = make_server()
        s.registry.execute = mock.Mock(
            return_value={"ok": True, "message": "done"})
        call(s, "read_file", {"path": "x.txt"})
        s.registry.execute.assert_called_once_with(
            "read_file", {"path": "x.txt"})


if __name__ == "__main__":
    unittest.main()
