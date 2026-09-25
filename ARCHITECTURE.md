# ALIX-Agent Architecture

## Overview

ALIX-Agent is a personal AI agent built around a strict layered
architecture with **vertical feature slices**. Every tool the agent can
call lives in exactly one slice under `features/`; there are no
old-style dispatch branches left in the agent core.

```
┌─────────────────────────────────────────────────────┐
│  Interfaces:  ALIXAgent.run()  │  mcp_server.py     │
│  (JSON-RPC 2.0 over stdio)                              │
├─────────────────────────────────────────────────────┤
│  Application: features/<slice>/                         │
│  DTO → ports → use-case (deny-before-runner)            │
├─────────────────────────────────────────────────────┤
│  Infrastructure: adapters                               │
│  policy_*_authorization  │  *_runner → hardened engines │
├─────────────────────────────────────────────────────┤
│  Hardened engines: SafeExecutor │ tools/web.py │ Memory │
├─────────────────────────────────────────────────────┤
│  Domain: domain/rules/ (pure functions, no I/O)        │
│  Cross-cutting: core/policy.py (fail-closed Policy)     │
└─────────────────────────────────────────────────────┘
```

## Vertical slices (`features/`)

Each slice owns one capability area end to end:

| Slice | Tools |
|---|---|
| `file_access` | `read_file`, `write_file`, `list_files`, `delete_file`, `search_files`, `verify_file`, `create_directory` |
| `command_execution` | `run_command`, `run_python` |
| `system` | `system_info`, `git_status` |
| `web` | `web_search`, `web_fetch` |
| `memory` | `remember_fact` |

Inside a slice, the layers are:

- **`application/dto/`** — request objects (e.g. `ListFilesRequest(path, all)`).
  The DTO is the contract between the LLM-facing schema and the use case.
- **`application/ports/`** — two interfaces per tool:
  `*_authorization` (may this run?) and `*_runner` (do it).
- **`application/use_cases/`** — orchestration. **Deny-before-runner**:
  the authorization port is consulted first; a denial returns without
  ever touching the runner.
- **`infrastructure/adapters/`** — the ports implemented:
  `policy_*` adapters consult `Policy`; `*_runner` adapters **delegate**
  to the hardened engines (`SafeExecutor`, `tools/web.py`, `Memory`).
  Adapters never reimplement hardening.
- **`interfaces/controllers/`** — input coercion and validation
  (e.g. safe int parsing) before the DTO is built.
- **`composition.py`** — wires DTO → controller → use case → adapters
  into a single handler callable. No-arg builders for policy-independent
  tools (web).

## Wiring: slice → agent

```
features/*/composition.py
        │  build_*_handler(policy, …)
        ▼
core/feature_bridge.py
        │  build_migrated_tool_handlers(policy, memory=None)
        ▼
core/registry.py  (ToolRegistry)
        │  execute(name, args) → ExecutionResult
        ▼
core/agent.py  (_execute_tool_body)
        │  1. fetch migrated handlers
        │  2. run the matching handler
        │  3. fall back to unknown-tool
```

`ALIXAgent.run()` is the main loop: validate input → LLM → either a
final answer or tool calls → `execute_tool` (confirmation gate, audit,
untrusted-output wrapping) → `_apply_context_boundary` (P3.9) →
repeat until `MAX_ROUNDS`.

## Domain rules (`domain/`)

Pure functions, stdlib + self imports only (enforced by
`test_architecture_boundaries.py`):

- `domain/rules/sensitive_paths.py` — `is_sensitive_path(path, …)`.
  Single source of truth used by `Policy`, `SafeExecutor`, and
  `tools/filesystem`.
- `domain/rules/confirmation.py` — `requires_confirmation(tool_name, …)`.
  Write/execute/destructive permissions need explicit approval.

## Invariants (non-negotiable)

1. **Deny-before-runner** — no tool executes without passing authorization.
2. **Fail-closed** — `Policy` denies when a guarantee cannot be established;
   never weaken it to make tests pass.
3. **Adapters delegate** — hardening lives in `SafeExecutor` / `tools/web.py`;
   slices add structure, not new security logic.
4. **Layer boundaries** — `domain/` imports nothing from outer layers;
   `core/` reaches `features/` only through the bridge allowlist.
5. **Schema contract** — `ExecutionResult.to_dict()` uses `message`,
   not `error` (see `SCHEMA_CONTRACT.md`).
6. **Evidence over memory** — tool results outrank the model's internal
   knowledge for factual questions (system-prompt addendum).
7. **P3.9 context boundary** — aggregate context never exceeds
   `MAX_CONTEXT_CHARS`; oversized system content raises fail-closed.
8. **Untrusted data** — tool output is wrapped as DATA ONLY and
   `<tool_call>` tags in untrusted content are neutralized by the
   prompt guard (`core/prompt_guard.py`).

## LLM layer (`core/llm.py`)

- `LocalLLM` — talks to `llama-server` over HTTP. **Never raises**:
  every failure mode (HTTP/URL/timeout/bad JSON) returns an error dict.
- `HybridLLM` — tries OpenRouter (`max_retries + 1` attempts, backoff),
  then falls back to local. `_safe_error` redacts the API key from
  error text and truncates to 1000 chars.

## MCP server (`mcp_server.py`)

JSON-RPC 2.0 over stdio, backed by the same `ToolRegistry` + `Policy` +
`Memory` as the agent. Methods: `initialize`, `tools/list`,
`tools/call` (`alix_check_code` runs static AST screening — never
executes; `alix_search_memory`; any registry tool via policy-gated
dispatch). `process_line` never crashes the stdio loop.

## Testing standard

Evidence-based completion: implementation + meaningful behavioral /
security tests + real runtime verification = done. No fake tests, no
tests written only to raise coverage. `memory/memory.json` is live
runtime data — tests mock `Memory`, never touch the file.

## Dual-LLM router (`core/dual_llm.py`) <!-- DUAL_LLM_DOC -->

`DualLLM` replaces `HybridLLM` as the agent's engine with the same
`chat(messages, tools)` interface, plus optional `task=` / `sensitive=`
hints. Every call passes a deterministic `route()` decision:

1. **Sensitive** (explicit flag or auto-detected high-confidence
   secrets: API keys, tokens, passwords, private keys) → local only,
   fail-closed. If the local engine fails, the request is refused —
   never escalated to remote.
2. **Tools present** → remote (tool orchestration needs the strong
   model).
3. **`task` in `LOCAL_TASKS`** (`summarize`, `extract`, `format`,
   `classify`) → local. On local failure the request escalates to
   remote — the weak model tries where it suffices, the strong model
   catches its failures.
4. **Default** → remote (preserves pre-router behavior; no silent
   length heuristics — routing to local requires an explicit hint).

Routing decisions are audited (`llm_route`, `llm_route_escalated`,
`llm_route_fail_closed`) with the decision and reason only, never
message content. Ordinary PII (names, emails, phones) is deliberately
NOT auto-gated; callers that know better pass `sensitive=True`.
