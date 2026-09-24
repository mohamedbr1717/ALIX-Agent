#!/usr/bin/env python3
"""Tests: MCP confirmation gate.

The MCP server must require an explicit per-call `confirmed: true`
for tools where policy.requires_confirmation() is True (the registry
is Policy-gated but NOT confirmation-gated). The flag must be stripped
before args reach the tool.

Run from the repo root: python3 -m pytest test_mcp_confirmation.py -q
"""
from __future__ import annotations

import unittest
from unittest import mock

import mcp_server
from mcp_server import ALIXMCPServer


def make_server():
    with mock.patch.object(mcp_server, "Memory",
                           return_value=mock.Mock()):
        return ALIXMCPServer()


def call(server, name, arguments, msg_id=1):
    return server.handle_request({
        "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })


def result_text(res):
    return res["result"]["content"][0]["text"]


class TestMCPConfirmationGate(unittest.TestCase):
    def test_destructive_without_confirmed_denied(self):
        s = make_server()
        s.registry.execute = mock.Mock()
        res = call(s, "delete_file", {"path": "x.txt"})
        s.registry.execute.assert_not_called()
        self.assertIn("تأكيد", result_text(res))

    def test_destructive_with_confirmed_proceeds(self):
        s = make_server()
        s.registry.execute = mock.Mock(
            return_value={"ok": True, "message": "done"})
        res = call(s, "delete_file",
                   {"path": "x.txt", "confirmed": True})
        # The confirmed flag is stripped before reaching the tool.
        s.registry.execute.assert_called_once_with(
            "delete_file", {"path": "x.txt"})
        self.assertIn("done", result_text(res))

    def test_destructive_with_confirmed_false_denied(self):
        s = make_server()
        s.registry.execute = mock.Mock()
        res = call(s, "run_command",
                   {"command": "ls", "confirmed": False})
        s.registry.execute.assert_not_called()
        self.assertIn("تأكيد", result_text(res))

    def test_safe_tool_needs_no_confirmed(self):
        s = make_server()
        s.registry.execute = mock.Mock(
            return_value={"ok": True, "message": "done"})
        res = call(s, "system_info", {})
        s.registry.execute.assert_called_once_with("system_info", {})
        self.assertIn("done", result_text(res))

    def test_confirmed_not_required_for_read(self):
        s = make_server()
        s.registry.execute = mock.Mock(
            return_value={"ok": True, "message": "done"})
        call(s, "read_file", {"path": "x.txt"})
        s.registry.execute.assert_called_once_with(
            "read_file", {"path": "x.txt"})


if __name__ == "__main__":
    unittest.main()
