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

"""Tests: MCP confirmation gate — HMAC-signed capability tokens.

Destructive tools are hidden by default (opt-in via
ALIX_MCP_ALLOW_DESTRUCTIVE=1). When opted in, a self-asserted
`confirmed: true` boolean is NOT accepted: the client must present a
`confirmation_token` minted offline with ALIX_MCP_HMAC_KEY:

    python3 -m core.plan_signer --tools delete_file --ttl 3600

Run from the repo root: python3 -m pytest test_mcp_confirmation.py -q
"""


class TestMCPConfirmationToken(MCPHarness):
    def test_no_token_denied(self):
        s = self.make_server(opt_in_env())
        s.registry.execute = mock.Mock()
        res = self.call(s, "delete_file", {"path": "x.txt"})
        s.registry.execute.assert_not_called()
        self.assertIn("confirmation_token", result_text(res))

    def test_boolean_confirmed_no_longer_accepted(self):
        # The old self-asserted boolean must NOT pass the gate.
        s = self.make_server(opt_in_env())
        s.registry.execute = mock.Mock()
        res = self.call(s, "delete_file",
                        {"path": "x.txt", "confirmed": True})
        s.registry.execute.assert_not_called()
        self.assertIn("confirmation_token", result_text(res))

    def test_forged_token_denied(self):
        s = self.make_server(opt_in_env())
        s.registry.execute = mock.Mock()
        res = self.call(s, "delete_file", {
            "path": "x.txt",
            "confirmation_token": "v1.delete_file.9999999999.deadbeef",
        })
        s.registry.execute.assert_not_called()
        self.assertIn("confirmation_token", result_text(res))

    def test_valid_token_proceeds_and_is_stripped(self):
        s = self.make_server(opt_in_env())
        seen = {}

        def fake_execute(name, arguments):
            seen["args"] = arguments
            return {"ok": True, "message": "done"}

        s.registry.execute = fake_execute
        token = mint_token(["delete_file"], ttl_s=600, key=TEST_KEY)
        res = self.call(s, "delete_file",
                        {"path": "x.txt", "confirmation_token": token})
        self.assertNotIn("confirmation_token", seen["args"])
        self.assertEqual(seen["args"].get("path"), "x.txt")
        self.assertIn("done", result_text(res))

    def test_expired_token_denied(self):
        s = self.make_server(opt_in_env())
        s.registry.execute = mock.Mock()
        token = mint_token(["delete_file"], ttl_s=-10, key=TEST_KEY)
        res = self.call(s, "delete_file",
                        {"path": "x.txt", "confirmation_token": token})
        s.registry.execute.assert_not_called()

    def test_missing_hmac_key_fail_closed(self):
        s = self.make_server({"ALIX_MCP_ALLOW_DESTRUCTIVE": "1",
                              "ALIX_MCP_HMAC_KEY": ""})
        s.registry.execute = mock.Mock()
        res = self.call(s, "delete_file",
                        {"path": "x.txt", "confirmation_token": "whatever"})
        s.registry.execute.assert_not_called()
        self.assertIn("ALIX_MCP_HMAC_KEY", result_text(res))


if __name__ == "__main__":
    unittest.main()
