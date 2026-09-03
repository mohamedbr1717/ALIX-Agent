import json
import sys
from alix_v4_1_unified import ALIXv41Agent

class ALIXMCPServer:
    def __init__(self):
        self.agent = ALIXv41Agent()

    def get_tools_schema(self):
        return [
            {
                "name": "alix_execute_code",
                "description": "Evaluates code safety via AST Policy Enforcer and executes clean payloads.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code snippet to validate and execute."},
                        "context_query": {"type": "string", "description": "Optional search term to retrieve context prior to execution."}
                    },
                    "required": ["code"]
                }
            },
            {
                "name": "alix_search_memory",
                "description": "Queries the sub-millisecond vector store for relevant prior context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term for memory retrieval."}
                    },
                    "required": ["query"]
                }
            }
        ]

    def handle_request(self, request):
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "alix-mcp-server", "version": "4.1.0"}
                }
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tools_schema()}
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "alix_execute_code":
                res = self.agent.execute_task(args.get("code"), args.get("context_query"))
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}
                }

            elif tool_name == "alix_search_memory":
                matches, latency = self.agent.memory.search(args.get("query"))
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": json.dumps({"matches": matches, "latency_ms": latency}, ensure_ascii=False)}]}
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method {method} not found"}
        }

    def process_line(self, line):
        if not line.strip():
            return None
        try:
            req = json.loads(line)
            return self.handle_request(req)
        except Exception as e:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}

if __name__ == "__main__":
    server = ALIXMCPServer()
    for line in sys.stdin:
        resp = server.process_line(line)
        if resp:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
