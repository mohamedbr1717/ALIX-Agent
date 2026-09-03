import json
from mcp_server import ALIXMCPServer

def test_mcp_protocol():
    print("=" * 55)
    print("         ALIX MCP PROTOCOL SUITE VERIFICATION       ")
    print("=" * 55)
    
    server = ALIXMCPServer()

    # 1. اختبار المصافحة (Handshake / Initialize)
    init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    init_res = server.process_line(init_req)
    print(f"[1] MCP Initialize Handshake: {init_res['result']['serverInfo']['name']}")

    # 2. اختبار استكشاف الأدوات (Tools Listing)
    list_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    list_res = server.process_line(list_req)
    tools = [t["name"] for t in list_res["result"]["tools"]]
    print(f"[2] Discovered MCP Tools     : {tools}")

    # 3. اختبار استدعاء أداة تنفيذ الكود الآمن (Tool Execution - Clean)
    exec_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "alix_execute_code",
            "arguments": {"code": "y = [i * 2 for i in range(5)]"}
        }
    })
    exec_res = server.process_line(exec_req)
    content = json.loads(exec_res["result"]["content"][0]["text"])
    print(f"[3] Clean Code Tool Call     : Status = {content['status']} | Latency = {content['latency_ms']:.4f} ms")

    # 4. اختبار استدعاء أداة اعتراض الأكواد المحظورة (Tool Execution - Blocked)
    block_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "alix_execute_code",
            "arguments": {"code": "import sys"}
        }
    })
    block_res = server.process_line(block_req)
    content_blocked = json.loads(block_res["result"]["content"][0]["text"])
    print(f"[4] Malicious Tool Call      : Status = {content_blocked['status']} | Violations = {content_blocked['violations']}")
    print("=" * 55)

if __name__ == "__main__":
    test_mcp_protocol()
