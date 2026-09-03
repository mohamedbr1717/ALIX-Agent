import sys
import json
import io

# توجيه الطباعة العامة إلى stderr لحماية مجرى JSON-RPC على stdout
real_stdout = sys.stdout
sys.stdout = sys.stderr

from alix_v4_1_unified import ALIXv41Agent
from quantized_vector_store import QuantizedVectorEngine

class ALIXMCPServer:
    def process_line(self, line: str):
        if not line or not line.strip():
            return None
        import json
        try:
            req = json.loads(line)
        except Exception:
            return {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}
        
        for handler_name in ["handle_request", "process_request", "handle_json_rpc", "handle_jsonrpc", "dispatch"]:
            if hasattr(self, handler_name):
                try:
                    res = getattr(self, handler_name)(req)
                    if isinstance(res, dict):
                        return res
                except Exception as e:
                    return {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": req.get("id") if isinstance(req, dict) else None}
        
        req_id = req.get("id") if isinstance(req, dict) else None
        method = req.get("method", "") if isinstance(req, dict) else ""
        return {
            "jsonrpc": "2.0",
            "result": {"status": "success", "method": method, "params": req.get("params", {}) if isinstance(req, dict) else {}},
            "id": req_id
        }
    def __init__(self):
        self.agent = ALIXv41Agent()
        self.memory = QuantizedVectorEngine()
        self.memory.add_document("doc1", "ALIX AST sandbox execution policy")

    def send_response(self, response_dict):
        # كتابة الاستجابة النظيفة حصرياً على stdout الحقيقي
        real_stdout.write(json.dumps(response_dict) + "\n")
        real_stdout.flush()

    def handle_request(self, req):
        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "alix-mcp-server", "version": "5.0.0"}
                }
            }
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [
                        {
                            "name": "alix_execute_code",
                            "description": "Evaluates code safety via AST Policy Enforcer and executes clean payloads.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"code": {"type": "string"}},
                                "required": ["code"]
                            }
                        },
                        {
                            "name": "alix_search_memory",
                            "description": "Queries the quantized INT8 vector store.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"]
                            }
                        }
                    ]
                }
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            
            if tool_name == "alix_execute_code":
                res = self.agent.execute_task(args.get("code", ""))
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": str(res)}]}}
            elif tool_name == "alix_search_memory":
                matches, latency = self.memory.search(args.get("query", ""))
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": f"Matches: {matches}, Latency: {latency:.4f}ms"}]}}

        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}}

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                res = self.handle_request(req)
                self.send_response(res)
            except Exception as e:
                self.send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}})

if __name__ == "__main__":
    server = ALIXMCPServer()
    server.run()
