import unittest
import json
from vector_memory import LightweightVectorStore
from wasm_sandbox import WASMMicroSandbox
from mcp_server import ALIXMCPServer
from merkle_logger import MerkleAuditLogger
from quantized_vector_store import QuantizedVectorEngine

class TestV5FullCoverage(unittest.TestCase):

    def test_vector_memory_deep(self):
        store = LightweightVectorStore()
        store.add_document("doc1", "python AST sandbox policy")
        store.add_document("doc2", "vector memory TF-IDF indexing")
        results, latency = store.search("AST policy")
        self.assertTrue(len(results) > 0)
        self.assertGreaterEqual(latency, 0)
        store.search("nonexistent query term")

    def test_wasm_sandbox_deep(self):
        sandbox = WASMMicroSandbox(max_memory_mb=32, max_cpu_sec=2)
        sandbox._apply_rlimits()
        res_ok = sandbox.execute_wasm_payload("x = 10 + 20")
        self.assertEqual(res_ok["status"], "WASM_EXEC_SUCCESS")
        res_err = sandbox.execute_wasm_payload("y = 1 / 0")
        self.assertEqual(res_err["status"], "WASM_EXEC_TRAPPED")

    def test_mcp_server_deep(self):
        server = ALIXMCPServer()
        self.assertIsNone(server.process_line(""))
        self.assertIsNone(server.process_line("   \n"))
        err_res = server.process_line("invalid json {")
        self.assertIn("error", err_res)
        
        unk_res = server.process_line(json.dumps({"jsonrpc": "2.0", "id": 99, "method": "unknown/method"}))
        self.assertIn("error", unk_res)

        mem_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "alix_search_memory",
                "arguments": {"query": "AST policy"}
            }
        })
        mem_res = server.process_line(mem_req)
        self.assertIn("result", mem_res)

    def test_merkle_logger_tamper_branch(self):
        logger = MerkleAuditLogger()
        logger.log_execution("code1", "APPROVED", 0.1)
        logger.log_execution("code2", "BLOCKED", 0.2, ["Banned Import"])
        valid, _ = logger.verify_integrity()
        self.assertTrue(valid)

        # التلاعب المتعمد لاختبار شرط كشف التزوير
        logger.chain[1]["prev_hash"] = "corrupted_hash_value"
        valid_tampered, msg_tampered = logger.verify_integrity()
        self.assertFalse(valid_tampered)
        self.assertIn("Tampering detected", msg_tampered)

    def test_quantized_engine_deep(self):
        engine = QuantizedVectorEngine(vector_dim=32)
        engine.add_document("q1", "quantum computation test")
        engine.add_document("q2", "neural network optimization")
        matches, _ = engine.search("quantum", top_k=2)
        self.assertEqual(len(matches), 2)

if __name__ == "__main__":
    unittest.main()
