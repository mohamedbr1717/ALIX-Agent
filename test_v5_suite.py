import unittest
from alix_v4_1_unified import ALIXv41Agent
from mcp_server import ALIXMCPServer
from wasm_sandbox import WASMMicroSandbox
from merkle_logger import MerkleAuditLogger
from quantized_vector_store import QuantizedVectorEngine

class TestALIXV5Suite(unittest.TestCase):
    def test_agent_core(self):
        agent = ALIXv41Agent()
        res = agent.execute_task("a = 5")
        self.assertEqual(res["status"], "APPROVED")

    def test_mcp_server(self):
        server = ALIXMCPServer()
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        res = server.handle_request(req)
        self.assertIn("result", res)

    def test_wasm_sandbox(self):
        sandbox = WASMMicroSandbox()
        res = sandbox.execute_wasm_payload("val = 100")
        self.assertEqual(res["status"], "WASM_EXEC_SUCCESS")

    def test_merkle_logger(self):
        logger = MerkleAuditLogger()
        logger.log_execution("x = 10", "APPROVED", 0.5)
        valid, _ = logger.verify_integrity()
        self.assertTrue(valid)

    def test_quantized_memory(self):
        engine = QuantizedVectorEngine()
        engine.add_document("doc1", "ALIX engine")
        matches, _ = engine.search("ALIX")
        self.assertTrue(len(matches) > 0)

if __name__ == "__main__":
    unittest.main()
