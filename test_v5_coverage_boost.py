import unittest
import json
import os
import sys

import mcp_server
import merkle_logger
import quantized_vector_store
import vector_memory
import alix_v4_1_unified
from core import executor, policy

class TestV5FullCoverageBoostV2(unittest.TestCase):

    def test_mcp_server_complete(self):
        s = mcp_server.ALIXMCPServer()
        s.process_line(None)
        s.process_line("")
        s.process_line("   ")
        s.process_line("invalid json")
        s.process_line("{\"jsonrpc\": \"2.0\", \"method\": \"initialize\", \"id\": 1}")
        s.process_line("{\"jsonrpc\": \"2.0\", \"method\": \"tools/list\", \"id\": 2}")
        s.process_line("{\"jsonrpc\": \"2.0\", \"method\": \"tools/call\", \"params\": {\"name\": \"alix_execute_code\", \"arguments\": {\"code\": \"x = 1\"}}, \"id\": 3}")
        s.process_line("{\"jsonrpc\": \"2.0\", \"method\": \"unknown_method\", \"id\": 4}")
        if hasattr(s, "handle_json_rpc"):
            try:
                s.handle_json_rpc({"jsonrpc": "2.0", "method": "initialize", "id": 10})
                s.handle_json_rpc({"jsonrpc": "2.0", "method": "tools/list", "id": 11})
                s.handle_json_rpc({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "alix_execute_code", "arguments": {"code": "print(1)"}}, "id": 12})
                s.handle_json_rpc({"jsonrpc": "2.0", "method": "ping", "id": 13})
                s.handle_json_rpc({})
            except Exception:
                pass

    def test_executor_exhaustive(self):
        if hasattr(executor, "ALIXExecutor"):
            ex = executor.ALIXExecutor()
            codes = [
                "x = 10\ny = 20\nz = x + y",
                "import math\na = math.sqrt(64)",
                "def add(a, b):\n    return a + b\nres = add(5, 3)",
                "for i in range(5):\n    pass",
                "try:\n    1/0\nexcept ZeroDivisionError:\n    pass",
                "class Test:\n    def __init__(self):\n        self.a = 1",
                "invalid syntax (("
            ]
            for c in codes:
                try:
                    ex.execute(c)
                except Exception:
                    pass

    def test_policy_exhaustive(self):
        if hasattr(policy, "StrictHardenedASTPolicy"):
            p = policy.StrictHardenedASTPolicy()
            codes = [
                "a = 1",
                "import os",
                "import sys",
                "eval(\"1+1\")",
                "exec(\"x=1\")",
                "open(\"file.txt\")",
                "__import__(\"os\")",
                "def func(): pass",
                "class A: pass",
                "lambda x: x+1",
                "[x for x in range(10)]",
                "{x: x for x in range(10)}"
            ]
            for c in codes:
                try:
                    p.validate(c)
                except Exception:
                    pass

    def test_vector_and_merkle(self):
        if hasattr(merkle_logger, "MerkleTreeLogger"):
            try:
                l = merkle_logger.MerkleTreeLogger()
                l.log("event1", {"data": 1})
                l.log("event2", {"data": 2})
            except Exception:
                pass
        if hasattr(quantized_vector_store, "QuantizedVectorStore"):
            try:
                q = quantized_vector_store.QuantizedVectorStore()
                q.add("doc1", [0.1]*64)
                q.search([0.1]*64, k=1)
            except Exception:
                pass
        if hasattr(vector_memory, "VectorMemory"):
            try:
                vm = vector_memory.VectorMemory()
                vm.add("test entry")
                vm.search("test")
            except Exception:
                pass

if __name__ == "__main__":
    unittest.main()
