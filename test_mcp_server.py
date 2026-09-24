"""Behavioral tests for mcp_server.py — screen_code, handle_request,
process_line. No stdio, no network, no live memory writes.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mcp_server
from mcp_server import ALIXMCPServer, screen_code


POLICY = {
    "max_code_length": 1000,
    "banned_nodes": ["Import", "ImportFrom"],
    "banned_names": ["eval", "exec", "open"],
    "banned_attributes": ["system"],
}


def make_policy_file() -> str:
    p = Path(tempfile.mkdtemp()) / "policy.json"
    p.write_text(json.dumps(POLICY), encoding="utf-8")
    return str(p)


class TestScreenCode(unittest.TestCase):
    def setUp(self):
        self.policy = make_policy_file()

    def test_approved_clean_code(self):
        res = screen_code("y = [i * 2 for i in range(5)]", self.policy)
        self.assertEqual(res["status"], "APPROVED")
        self.assertEqual(res["violations"], [])

    def test_blocked_banned_node(self):
        res = screen_code("import os", self.policy)
        self.assertEqual(res["status"], "BLOCKED")
        self.assertTrue(any("Import" in v for v in res["violations"]))

    def test_blocked_banned_name(self):
        res = screen_code("eval('1+1')", self.policy)
        self.assertEqual(res["status"], "BLOCKED")
        self.assertTrue(any("eval" in v for v in res["violations"]))

    def test_blocked_syntax_error(self):
        res = screen_code("def broken(", self.policy)
        self.assertEqual(res["status"], "BLOCKED")

    def test_blocked_non_string(self):
        res = screen_code(123, self.policy)
        self.assertEqual(res["status"], "BLOCKED")

    def test_blocked_too_long(self):
        res = screen_code("x = 1\n" * 500, self.policy)
        self.assertEqual(res["status"], "BLOCKED")
        self.assertTrue(any("max_code_length" in v
                            for v in res["violations"]))

    def test_error_unreadable_policy(self):
        res = screen_code("x = 1", "/nonexistent/policy.json")
        self.assertEqual(res["status"], "ERROR")

    def test_never_executes(self):
        # If screening ever executed the code, this would be catastrophic.
        res = screen_code("__import__('os').system('echo PWNED')",
                          self.policy)
        self.assertEqual(res["status"], "BLOCKED")


class TestHandleRequest(unittest.TestCase):
    def make_server(self):
        with mock.patch.object(mcp_server, "Memory",
                               return_value=mock.Mock()):
            server = ALIXMCPServer()
        return server

    def test_non_dict(self):
        s = self.make_server()
        res = s.handle_request("not-a-dict")
        self.assertEqual(res["error"]["code"], -32600)

    def test_notification_no_response(self):
        s = self.make_server()
        res = s.handle_request({"jsonrpc": "2.0",
                                "method": "notifications/initialized"})
        self.assertIsNone(res)

    def test_initialize(self):
        s = self.make_server()
        res = s.handle_request({"jsonrpc": "2.0", "id": 1,
                                "method": "initialize", "params": {}})
        self.assertEqual(res["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(res["result"]["serverInfo"]["name"],
                         "alix-mcp-server")

    def test_tools_list(self):
        # Destructive tools are hidden by default; opt in to verify
        # migrated registry tools are advertised when allowed.
        with mock.patch.dict(os.environ,
                             {"ALIX_MCP_ALLOW_DESTRUCTIVE": "1"}):
            s = self.make_server()
        res = s.handle_request({"jsonrpc": "2.0", "id": 2,
                                "method": "tools/list", "params": {}})
        names = [t["name"] for t in res["result"]["tools"]]
        # A migrated registry tool must be advertised.
        self.assertIn("write_file", names)
        for t in res["result"]["tools"]:
            self.assertIn("name", t)

    def test_call_check_code(self):
        s = self.make_server()
        with mock.patch.object(
            mcp_server, "screen_code",
            return_value={"status": "APPROVED", "violations": []},
        ) as sc:
            res = s.handle_request({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "alix_check_code",
                           "arguments": {"code": "x = 1"}},
            })
        sc.assert_called_once_with("x = 1")
        text = res["result"]["content"][0]["text"]
        self.assertIn("APPROVED", text)

    def test_call_search_memory(self):
        s = self.make_server()
        s.memory.search.return_value = [{"fact": "likes tea"}]
        res = s.handle_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "alix_search_memory",
                       "arguments": {"query": "tea", "limit": "5"}},
        })
        s.memory.search.assert_called_once_with("tea", limit=5)
        text = res["result"]["content"][0]["text"]
        self.assertIn("likes tea", text)

    def test_call_search_memory_bad_limit(self):
        s = self.make_server()
        s.memory.search.return_value = []
        s.handle_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "alix_search_memory",
                       "arguments": {"query": "x", "limit": "junk"}},
        })
        # Falls back to the default limit instead of crashing.
        s.memory.search.assert_called_once_with("x", limit=10)

    def test_call_registry_tool(self):
        s = self.make_server()
        s.registry.execute = mock.Mock(
            return_value={"ok": True, "message": "done"})
        res = s.handle_request({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "system_info", "arguments": {}},
        })
        s.registry.execute.assert_called_once_with("system_info", {})
        text = res["result"]["content"][0]["text"]
        self.assertIn("done", text)

    def test_call_unknown_tool(self):
        s = self.make_server()
        res = s.handle_request({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "nope_not_a_tool", "arguments": {}},
        })
        self.assertEqual(res["error"]["code"], -32601)

    def test_unknown_method(self):
        s = self.make_server()
        res = s.handle_request({"jsonrpc": "2.0", "id": 7,
                                "method": "frobnicate", "params": {}})
        self.assertEqual(res["error"]["code"], -32601)


class TestProcessLine(unittest.TestCase):
    def make_server(self):
        with mock.patch.object(mcp_server, "Memory",
                               return_value=mock.Mock()):
            return ALIXMCPServer()

    def test_empty(self):
        s = self.make_server()
        self.assertIsNone(s.process_line(""))
        self.assertIsNone(s.process_line("   "))

    def test_bad_json(self):
        s = self.make_server()
        res = s.process_line("{not json")
        self.assertEqual(res["error"]["code"], -32700)
        self.assertIsNone(res["id"])

    def test_exception_never_crashes(self):
        s = self.make_server()
        with mock.patch.object(s, "handle_request",
                               side_effect=RuntimeError("boom")):
            res = s.process_line(
                json.dumps({"jsonrpc": "2.0", "id": 9,
                            "method": "tools/list"}))
        self.assertEqual(res["error"]["code"], -32603)
        self.assertEqual(res["id"], 9)


if __name__ == "__main__":
    unittest.main()
