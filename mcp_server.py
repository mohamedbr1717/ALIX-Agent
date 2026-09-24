#!/usr/bin/env python3
"""
ALIX MCP Server -- rebuilt on the new core (v5).

Exposes ALIX over JSON-RPC 2.0 on stdio for MCP clients
(e.g. Claude Desktop).

Replaces the old implementation which imported the removed
modules ``alix_v4_1_unified`` and ``quantized_vector_store``.
This version is built on:

  * ``core.registry.ToolRegistry`` -- canonical tool dispatch,
    always gated by ``core.policy.Policy`` (same security
    posture as the agent itself).
  * ``core.memory.Memory``          -- persistent JSON memory store.
  * ``core.agent.ALIXAgent``        -- imported lazily; only needed
    for future chat features. Requires the ``openai`` package.

Protocol compatibility
----------------------
The JSON-RPC method names are unchanged: ``initialize``,
``tools/list`` and ``tools/call``. The two legacy tools keep
their names:

  * ``alix_check_code``   -- static AST screening of Python code.
    Same APPROVED/BLOCKED verdict shape as before
    (``status`` / ``violations`` / ``latency_ms``). It NEVER
    executes the code. NOTE: the screen is a denylist heuristic,
    not a sandbox -- an APPROVED verdict must not be treated as
    "safe to run".
  * ``alix_search_memory`` -- now searches the core JSON memory
    store (``core.memory.Memory``) instead of the removed
    quantized INT8 vector engine. Returns matches as JSON.

Additionally, the agent's registered tools are exposed:
``list_files``, ``read_file``, ``write_file``,
``create_directory``, ``delete_file``, ``run_python``,
``run_command``, ``system_info``, ``git_status``.
Every call goes through ``ToolRegistry.execute`` so the Policy
allowlist, capability gates and workspace confinement apply.
"""

import ast
import json
import os
import sys
import time
from pathlib import Path

# ------------------------------------------------------------------
# Keep stdout clean: JSON-RPC frames are the ONLY thing allowed on
# the real stdout. Everything else (prints, logs) goes to stderr.
# ------------------------------------------------------------------
real_stdout = sys.stdout
sys.stdout = sys.stderr

# Make sure ``core`` / ``tools`` / ``features`` are importable when
# this file is executed directly (``python mcp_server.py``) from the
# project directory.
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.memory import Memory
from core.policy import Policy
from core.registry import ToolRegistry

# Optional: full agent (needs the ``openai`` package + API key).
# The MCP tools below do NOT need it, so the server stays usable
# on a fresh Termux install.
try:
    from core.agent import ALIXAgent  # noqa: F401
    ALIX_AGENT_AVAILABLE = True
except Exception:  # ImportError or missing third-party dep
    ALIXAgent = None
    ALIX_AGENT_AVAILABLE = False


# ------------------------------------------------------------------
# Static AST screening (same semantics as the old
# policy_watcher.LivePolicyEngine.inspect_code).
# ------------------------------------------------------------------
def screen_code(code: str, policy_path: str = "policy.json") -> dict:
    """Return APPROVED/BLOCKED verdict for Python *source* (never executed)."""
    started = time.perf_counter()

    policy_file = Path(policy_path)
    if not policy_file.is_absolute():
        policy_file = BASE_DIR / policy_path
    try:
        policy_data = json.loads(policy_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "ERROR",
            "violations": [f"Policy file unreadable: {exc}"],
            "latency_ms": (time.perf_counter() - started) * 1000,
        }

    if not isinstance(code, str):
        return {
            "status": "BLOCKED",
            "violations": ["Invalid input: code must be a string."],
            "latency_ms": (time.perf_counter() - started) * 1000,
        }

    max_len = policy_data.get("max_code_length")
    if isinstance(max_len, int) and len(code) > max_len:
        return {
            "status": "BLOCKED",
            "violations": [f"Rejected: code exceeds max_code_length ({max_len})."],
            "latency_ms": (time.perf_counter() - started) * 1000,
        }

    try:
        parsed = ast.parse(code)
    except SyntaxError as exc:
        return {
            "status": "BLOCKED",
            "violations": [f"Rejected: code does not parse ({exc})."],
            "latency_ms": (time.perf_counter() - started) * 1000,
        }

    banned_nodes = set(policy_data.get("banned_nodes", []))
    banned_names = set(policy_data.get("banned_names", []))
    banned_attrs = set(policy_data.get("banned_attributes", []))

    violations = []
    for node in ast.walk(parsed):
        if type(node).__name__ in banned_nodes:
            violations.append(f"Banned Node: {type(node).__name__}")
        elif isinstance(node, ast.Name) and node.id in banned_names:
            violations.append(f"Forbidden System Call: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in banned_attrs:
            violations.append(f"Forbidden Attribute Access: {node.attr}")

    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "status": "BLOCKED" if violations else "APPROVED",
        "violations": violations,
        "latency_ms": latency_ms,
    }


# ------------------------------------------------------------------
# MCP tool catalogue
# ------------------------------------------------------------------
LEGACY_TOOLS = [
    {
        "name": "alix_check_code",
        "description": (
            "Static AST screening only -- flags Python code containing "
            "banned imports/names/attributes from policy.json. Does NOT "
            "execute the code, and an APPROVED verdict does NOT mean the "
            "code is safe to run (the screen is a bypassable denylist, "
            "not a sandbox)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "alix_search_memory",
        "description": (
            "Searches ALIX's persistent memory (facts and preferences) "
            "for a text query. Replaces the old quantized vector search."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
]

# Registry tools exposed over MCP. Schemas mirror
# Policy.tool_argument_schema. All calls are Policy-gated.
REGISTRY_TOOL_SCHEMAS = {
    "list_files": {
        "description": "List files inside the agent workspace.",
        "properties": {"path": {"type": "string", "default": "."}},
        "required": ["path"],
    },
    "read_file": {
        "description": "Read a file from the agent workspace (optional line range).",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path"],
    },
    "write_file": {
        "description": "Write content to a file inside the agent workspace.",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    "create_directory": {
        "description": "Create a directory inside the agent workspace.",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    "delete_file": {
        "description": "Delete a file inside the agent workspace.",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    "run_python": {
        "description": (
            "Execute a Python script file inside the policy sandbox. "
            "Disabled by default via the capability gate."
        ),
        "properties": {"script_path": {"type": "string"}},
        "required": ["script_path"],
    },
    "run_command": {
        "description": "Run a restricted shell command inside the workspace.",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    "system_info": {
        "description": "Return basic system information.",
        "properties": {},
        "required": [],
    },
    "git_status": {
        "description": "Run a read-only git command (status/log/diff).",
        "properties": {"action": {"type": "string", "default": "status"}},
        "required": [],
    },
}


class ALIXMCPServer:
    """JSON-RPC 2.0 over stdio, backed by the new core."""

    def __init__(self):
        self.policy = Policy()
        self.registry = ToolRegistry(self.policy)
        self.memory = Memory()
        # Threat model: MCP clients are NOT trusted. A malicious client
        # can trivially assert `confirmed: true`, so destructive tools
        # (those requiring confirmation) are hidden and denied unless
        # the operator explicitly opts in. Fail-closed by default.
        self.allow_destructive = os.environ.get(
            "ALIX_MCP_ALLOW_DESTRUCTIVE", "").lower() in (
                "1", "true", "yes")
        # Seed a context fact so memory search has something meaningful.
        try:
            self.memory.add_fact("ALIX MCP server uses core policy AST screening")
        except Exception:
            pass

    # -- transport -------------------------------------------------
    def send_response(self, response_dict):
        real_stdout.write(json.dumps(response_dict) + "\n")
        real_stdout.flush()

    # -- JSON-RPC helpers ------------------------------------------
    @staticmethod
    def _ok(msg_id, result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _err(msg_id, code, message):
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    def _text_result(payload) -> dict:
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False)
        return {"content": [{"type": "text", "text": payload}]}

    # -- protocol ---------------------------------------------------
    def handle_request(self, req):
        if not isinstance(req, dict):
            return self._err(None, -32600, "Invalid Request")

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {}) or {}

        # Notifications (no id): acknowledge silently, no response frame.
        if "id" not in req:
            return None

        if method == "initialize":
            return self._ok(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "alix-mcp-server",
                        "version": "5.1.0",
                    },
                },
            )

        if method == "tools/list":
            tools = list(LEGACY_TOOLS)
            for name in self.registry.names():
                if (not self.allow_destructive
                        and self.policy.requires_confirmation(name)):
                    continue
                schema = REGISTRY_TOOL_SCHEMAS.get(name)
                if schema is None:
                    continue
                tools.append(
                    {
                        "name": name,
                        "description": schema["description"],
                        "inputSchema": {
                            "type": "object",
                            "properties": schema["properties"],
                            "required": schema["required"],
                        },
                    }
                )
            return self._ok(msg_id, {"tools": tools})

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {}) or {}

            if tool_name == "alix_check_code":
                # Static screening only -- never executes the code.
                verdict = screen_code(args.get("code", ""))
                return self._ok(msg_id, self._text_result(verdict))

            if tool_name == "alix_search_memory":
                started = time.perf_counter()
                try:
                    limit = int(args.get("limit", 10))
                except (TypeError, ValueError):
                    limit = 10
                matches = self.memory.search(args.get("query", ""), limit=limit)
                payload = {
                    "matches": matches,
                    "count": len(matches),
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
                return self._ok(msg_id, self._text_result(payload))

            if self.registry.has(tool_name):
                # Confirmation gate: the registry is Policy-gated but
                # NOT confirmation-gated (confirmation is the Agent's
                # responsibility). MCP clients must explicitly confirm
                # destructive tools on every call.
                if self.policy.requires_confirmation(tool_name):
                    if not self.allow_destructive:
                        return self._ok(
                            msg_id,
                            self._text_result(
                                {
                                    "ok": False,
                                    "action": tool_name,
                                    "message": (
                                        f"الأداة '{tool_name}' مدمرة "
                                        "ومحظورة عبر MCP افتراضيًا. "
                                        "فعّل ALIX_MCP_ALLOW_DESTRUCTIVE=1 "
                                        "للسماح بها."
                                    ),
                                }
                            ),
                        )
                    if args.get("confirmed") is not True:
                        return self._ok(
                            msg_id,
                            self._text_result(
                                {
                                    "ok": False,
                                    "action": tool_name,
                                    "message": (
                                        f"الأداة '{tool_name}' تتطلب "
                                        "تأكيدًا صريحًا. أعد الإرسال مع "
                                        "confirmed=true."
                                    ),
                                }
                            ),
                        )
                    args = {
                        k: v for k, v in args.items() if k != "confirmed"
                    }
                # Policy-gated dispatch; returns the canonical
                # ExecutionResult dict (ok/action/message/...).
                result = self.registry.execute(tool_name, args)
                return self._ok(msg_id, self._text_result(result))

            return self._err(
                msg_id, -32601, f"Method not found: {method or tool_name}"
            )

        return self._err(msg_id, -32601, f"Method not found: {method}")

    # Backwards-compatible entry point used by the old test suite.
    def process_line(self, line: str):
        if not line or not line.strip():
            return None
        try:
            req = json.loads(line)
        except Exception:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            }
        try:
            return self.handle_request(req)
        except Exception as exc:  # never crash the stdio loop
            msg_id = req.get("id") if isinstance(req, dict) else None
            return self._err(msg_id, -32603, str(exc))

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                res = self.handle_request(req)
                if res is not None:  # notifications get no response
                    self.send_response(res)
            except Exception as exc:
                self.send_response(self._err(None, -32700, str(exc)))


if __name__ == "__main__":
    server = ALIXMCPServer()
    server.run()
