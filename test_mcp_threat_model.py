#!/usr/bin/env python3
from __future__ import annotations

import os
import unittest
from unittest import mock

import mcp_server
from core.plan_signer import mint as mint_token
from mcp_server import ALIXMCPServer

TEST_KEY = "test-hmac-key-do-not-use-in-prod"


def opt_in_env():
    return {"ALIX_MCP_ALLOW_DESTRUCTIVE": "1", "ALIX_MCP_HMAC_KEY": TEST_KEY}


def result_text(res):
    return res["result"]["content"][0]["text"]


class MCPHarness(unittest.TestCase):
    """Env patching stays active for the whole test.

    The server reads ALIX_MCP_ALLOW_DESTRUCTIVE at construction but
    ALIX_MCP_HMAC_KEY on every tools/call, so the patch must outlive
    make_server(). patcher.stop is registered as a cleanup.
    """

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

"""Tests: MCP threat model — destructive tools hidden/denied by default;
opt-in via ALIX_MCP_ALLOW_DESTRUCTIVE=1; per-call HMAC capability token.

The MCP client is untrusted and must not be able to self-confirm a
destructive call: the `confirmed: true` boolean is dead. Tokens are minted
offline: python3 -m core.plan_signer --tools delete_file --ttl 3600

Run from the repo root: python3 -m pytest test_mcp_threat_model.py -q
"""


class TestMCPThreatModel(MCPHarness):
    def list_names(self, server):
        res = server.handle_request({"jsonrpc": "2.0", "id": 1,
                                     "method": "tools/list", "params": {}})
        return [t["name"] for t in res["result"]["tools"]]

    def test_destructive_hidden_from_list_by_default(self):
        s = self.make_server()
        names = self.list_names(s)
        for destructive in ("delete_file", "run_command", "run_python",
                            "write_file", "create_directory"):
            self.assertNotIn(destructive, names)
        self.assertIn("read_file", names)

    def test_destructive_denied_in_call_by_default(self):
        # Even WITH a token and the old boolean: default deny wins.
        s = self.make_server()
        s.registry.execute = mock.Mock()
        res = self.call(s, "delete_file", {
            "path": "x.txt",
            "confirmed": True,
            "confirmation_token": mint_token(["delete_file"], ttl_s=600,
                                             key=TEST_KEY),
        })
        s.registry.execute.assert_not_called()
        self.assertIn("ALIX_MCP_ALLOW_DESTRUCTIVE", result_text(res))

    def test_opt_in_exposes_in_list(self):
        s = self.make_server(opt_in_env())
        names = self.list_names(s)
        self.assertIn("delete_file", names)

    def test_opt_in_with_valid_token_executes(self):
        s = self.make_server(opt_in_env())
        s.registry.execute = mock.Mock(
            return_value={"ok": True, "message": "done"})
        token = mint_token(["delete_file"], ttl_s=600, key=TEST_KEY)
        res = self.call(s, "delete_file",
                        {"path": "x.txt", "confirmation_token": token})
        s.registry.execute.assert_called_once()
        self.assertIn("done", result_text(res))

    def test_opt_in_with_wrong_scope_token_denied(self):
        # Token minted for write_file must NOT authorize delete_file.
        s = self.make_server(opt_in_env())
        s.registry.execute = mock.Mock()
        token = mint_token(["write_file"], ttl_s=600, key=TEST_KEY)
        res = self.call(s, "delete_file",
                        {"path": "x.txt", "confirmation_token": token})
        s.registry.execute.assert_not_called()
        self.assertIn("confirmation_token", result_text(res))


if __name__ == "__main__":
    unittest.main()
