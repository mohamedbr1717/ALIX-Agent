"""ALIX native context compressor — stdlib only.

Reduces token consumption before sending to Groq/OpenAI-compatible APIs.
Pipeline: normalize → dedup → trim old tool results → budget window → digest.

Design goals:
- Zero external dependencies (stdlib only).
- Preserves tool_call/tool result integrity (never orphans).
- Stable ordering for Groq prompt caching (system first, tools stable).
- Fail-closed: on any error, returns messages unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re


# ---------------------------------------------------------------------------
# Token estimation (heuristic: ~4 chars per token for English/Arabic mix)
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate. Use API `usage` for exact accounting."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def message_tokens(msg: dict) -> int:
    """Estimate tokens for a single message dict."""
    total = 0
    content = msg.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and "text" in part:
                total += estimate_tokens(str(part["text"]))
    # tool_calls overhead
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
        total += estimate_tokens(str(fn.get("name", "")))
        total += estimate_tokens(str(fn.get("arguments", "")))
        total += 20  # structural overhead
    total += 10  # role + structure overhead
    return total


# ---------------------------------------------------------------------------
# Stage 1: Normalize
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Collapse redundant whitespace outside code fences."""
    if not text or "```" not in text:
        return re.sub(r"[ \t]+", " ", text).strip() if text else text
    # Preserve code fences verbatim
    parts = text.split("```")
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"[ \t]+", " ", parts[i])
    return "```".join(parts).strip()


def normalize_message(msg: dict) -> dict:
    """Return a copy with normalized content."""
    msg = dict(msg)
    content = msg.get("content")
    if isinstance(content, str) and content:
        msg["content"] = normalize_text(content)
    return msg


# ---------------------------------------------------------------------------
# Stage 2: Dedup
# ---------------------------------------------------------------------------

def _content_hash(msg: dict) -> str:
    """Hash of role + content for dedup detection."""
    role = msg.get("role", "")
    content = msg.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(f"{role}:{content}".encode("utf-8")).hexdigest()[:16]


def dedup_messages(messages: list[dict]) -> list[dict]:
    """Remove consecutive duplicate messages (keeps first occurrence).

    Only removes EXACT consecutive duplicates — safe for tool flows.
    """
    if len(messages) < 2:
        return messages
    result = [messages[0]]
    prev_hash = _content_hash(messages[0])
    for msg in messages[1:]:
        h = _content_hash(msg)
        # Never dedup tool results or tool calls (integrity)
        if msg.get("role") in ("tool",):
            result.append(msg)
            prev_hash = h
            continue
        if h == prev_hash and msg.get("role") == result[-1].get("role"):
            continue  # skip duplicate
        result.append(msg)
        prev_hash = h
    return result


# ---------------------------------------------------------------------------
# Stage 3: Trim old tool results
# ---------------------------------------------------------------------------

TOOL_RESULT_KEEP_CHARS = 500


def trim_tool_result(content: str, keep: int = TOOL_RESULT_KEEP_CHARS) -> str:
    """Head+tail trim: keep opening and closing, cut the middle."""
    if not isinstance(content, str) or len(content) <= keep:
        return content
    omitted = len(content) - keep
    head = keep // 2
    tail = keep - head
    return (
        content[:head]
        + f"\n[... {omitted} chars omitted ...]\n"
        + content[-tail:]
    )


def trim_old_tool_results(
    messages: list[dict],
    preserve_recent: int = 2,
    keep_chars: int = TOOL_RESULT_KEEP_CHARS,
) -> list[dict]:
    """Clamp older tool results; keep the most recent intact.

    Never touches assistant messages with tool_calls (integrity).
    """
    # Find indices of tool messages
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if len(tool_indices) <= preserve_recent:
        return messages
    # Trim all but the most recent `preserve_recent`
    trim_up_to = len(tool_indices) - preserve_recent
    result = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool" and i in tool_indices[:trim_up_to]:
            msg = dict(msg)
            msg["content"] = trim_tool_result(str(msg.get("content", "")), keep_chars)
        result.append(msg)
    return result


# ---------------------------------------------------------------------------
# Stage 4: Budget window + extractive digest
# ---------------------------------------------------------------------------

def extractive_digest(messages: list[dict], max_items: int = 8) -> str:
    """Build a compact digest of dropped messages.

    Extracts: tool names called, key topics, error mentions.
    Pure extractive — no LLM needed.
    """
    items = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                name = fn.get("name", "?")
                items.append(f"Called tool: {name}")
        elif role == "user":
            content = str(msg.get("content", ""))[:120]
            if content.strip():
                items.append(f"User: {content.strip()}")
        elif role == "tool":
            content = str(msg.get("content", ""))
            # Extract error mentions
            if "error" in content.lower() or "خطأ" in content:
                items.append(f"Tool result (error): {content[:100]}")
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    lines = unique[:max_items]
    if not lines:
        return "[Earlier conversation context]"
    return "[Earlier context — {} messages summarized]\n".format(len(messages)) + "\n".join(
        f"- {line}" for line in lines
    )


def apply_budget_window(
    messages: list[dict],
    max_tokens: int = 6000,
) -> list[dict]:
    """Keep messages within token budget, starting from the most recent.

    Rules:
    - System message always kept (first).
    - Latest user message always kept (never drop all user messages).
    - Dropped prefix → extractive digest (not silent deletion).
    - Never split assistant tool_calls from their tool results.
    """
    if not messages:
        return messages

    # Separate system message
    system_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    # Quick check: if already within budget, return as-is
    total = sum(message_tokens(m) for m in messages)
    if total <= max_tokens:
        return messages

    # Walk backwards, keeping messages until budget exhausted
    kept = []
    used = sum(message_tokens(m) for m in system_msgs)
    # Reserve space for digest
    digest_reserve = 300
    budget = max_tokens - digest_reserve

    # Always keep the last message (usually latest user or assistant)
    # Then walk backwards
    i = len(rest) - 1
    # Find last user message index — must keep at least one user message
    last_user_idx = None
    for idx in range(len(rest) - 1, -1, -1):
        if rest[idx].get("role") == "user":
            last_user_idx = idx
            break

    kept_indices = set()
    # Phase 1: keep from the end backwards within budget
    while i >= 0 and used < budget:
        msg = rest[i]
        tok = message_tokens(msg)
        # Don't break tool_call/tool pairs: if this is a tool result,
        # also keep its assistant tool_call message
        if msg.get("role") == "tool":
            # Find the matching assistant message with tool_calls
            tool_call_id = msg.get("tool_call_id")
            # Keep both if they fit
            pair_tok = tok
            pair_idx = None
            for j in range(i - 1, -1, -1):
                m2 = rest[j]
                if m2.get("role") == "assistant" and m2.get("tool_calls"):
                    tc_ids = [
                        tc.get("id") for tc in m2["tool_calls"]
                        if isinstance(tc, dict)
                    ]
                    if tool_call_id in tc_ids:
                        pair_tok += message_tokens(m2)
                        pair_idx = j
                        break
                if m2.get("role") == "user":
                    break  # don't cross user boundary
            if used + pair_tok <= budget:
                kept_indices.add(i)
                if pair_idx is not None:
                    kept_indices.add(pair_idx)
                used += pair_tok
            # else: skip this pair (will be digested)
        elif i not in kept_indices:
            if used + tok <= budget:
                kept_indices.add(i)
                used += tok
        i -= 1

    # Ensure at least one user message is kept
    if last_user_idx is not None and last_user_idx not in kept_indices:
        # Force-keep it, drop oldest kept to make room if needed
        kept_indices.add(last_user_idx)

    kept_sorted = sorted(kept_indices)
    dropped = [rest[i] for i in range(len(rest)) if i not in kept_indices]

    result = list(system_msgs)
    if dropped:
        digest = extractive_digest(dropped)
        result.append({"role": "user", "content": digest})
    for idx in kept_sorted:
        result.append(rest[idx])
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

class ContextCompressor:
    """Native ALIX context compressor (stdlib only)."""

    def __init__(
        self,
        max_tokens: int = 6000,
        tool_result_keep_chars: int = TOOL_RESULT_KEEP_CHARS,
        preserve_recent_tools: int = 2,
    ):
        self.max_tokens = max_tokens
        self.tool_result_keep_chars = tool_result_keep_chars
        self.preserve_recent_tools = preserve_recent_tools
        self.last_stats: dict = {}

    def compress(self, messages: list[dict]) -> list[dict]:
        """Run the full pipeline. Fail-closed: returns input on error."""
        try:
            original_tokens = sum(message_tokens(m) for m in messages)

            # Stage 1: normalize
            msgs = [normalize_message(m) for m in messages]
            # Stage 2: dedup
            msgs = dedup_messages(msgs)
            # Stage 3: trim old tool results
            msgs = trim_old_tool_results(
                msgs,
                preserve_recent=self.preserve_recent_tools,
                keep_chars=self.tool_result_keep_chars,
            )
            # Stage 4: budget window
            msgs = apply_budget_window(msgs, max_tokens=self.max_tokens)

            compressed_tokens = sum(message_tokens(m) for m in msgs)
            self.last_stats = {
                "original_tokens": original_tokens,
                "compressed_tokens": compressed_tokens,
                "saved_tokens": original_tokens - compressed_tokens,
                "savings_pct": (
                    round(
                        100 * (original_tokens - compressed_tokens) / original_tokens, 1
                    )
                    if original_tokens > 0 else 0
                ),
                "original_messages": len(messages),
                "compressed_messages": len(msgs),
            }
            return msgs
        except Exception:
            # Fail-closed: return original messages unchanged
            self.last_stats = {"error": "compression failed, passthrough"}
            return messages
