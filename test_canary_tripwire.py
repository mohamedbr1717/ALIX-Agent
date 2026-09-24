#!/usr/bin/env python3
"""Canary tripwire: honeytoken appearing in tool-call arguments is denied
fail-closed (the published honeytoken is fake; its presence in args means
the model is acting on injected content or leaking the prompt).

Run from the repo root: python3 -m pytest test_canary_tripwire.py -q
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import mcp_server
from core.canary import find_canary, get_canary
from core.prompt_guard import SYSTEM_GUARD_ADDENDUM
from mcp_server import ALIXMCPServer

CANARY = get_canary()


class MCPHarness(unittest.TestCase):
    def make_server(self, env=None):
        env = env or {}
        patcher = mock.patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        if "ALIX_MCP_ALLOW_DESTRUCTIVE" not in env:
            os.environ.pop("ALIX_MCP_ALLOW_DESTRUCTIVE", None)
        with mock.patch.object(mcp_server, "Memory",
                               return_value=mock.Mock()):
            return ALIXMCPServer()

    def call(self, server, name, arguments, msg_id=1):
        return server.handle_request({
            "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })


def result_text(res):
    return res["result"]["content"][0]["text"]


class TestFindCanary(unittest.TestCase):
    def test_direct_hit(self):
        self.assertEqual(find_canary({"path": CANARY}), CANARY)

    def test_substring_hit(self):
        self.assertEqual(find_canary({"path": f"/tmp/{CANARY}/x"}), CANARY)

    def test_nested_hit(self):
        self.assertEqual(find_canary({"a": [{"b": CANARY}]}), CANARY)

    def test_tuple_hit(self):
        self.assertEqual(find_canary((CANARY,)), CANARY)

    def test_clean_dict(self):
        self.assertIsNone(find_canary({"path": "/tmp/x", "n": 42}))

    def test_non_string_values_ignored(self):
        self.assertIsNone(find_canary({"n": 42, "b": True, "z": None}))


class TestCanaryGate(MCPHarness):
    def test_tool_args_with_canary_denied(self):
        s = self.make_server()
        res = self.call(s, "read_file", {"path": CANARY})
        self.assertIn("CANARY TRIPWIRE", result_text(res))

    def test_embedded_canary_denied(self):
        s = self.make_server()
        res = self.call(s, "read_file", {"path": f"prefix-{CANARY}"})
        self.assertIn("CANARY TRIPWIRE", result_text(res))

    def test_clean_args_pass_gate(self):
        # A normal (failing) read must NOT trip the canary.
        s = self.make_server()
        res = self.call(s, "read_file", {"path": "/tmp/nope-not-here-xyz"})
        self.assertNotIn("CANARY TRIPWIRE", result_text(res))

    def test_honeytoken_published_in_system_prompt(self):
        self.assertIn(CANARY, SYSTEM_GUARD_ADDENDUM)


if __name__ == "__main__":
    unittest.main()
