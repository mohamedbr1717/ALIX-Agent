"""Context compressor for the ALIX dual-LLM router (v1).

When a request is too large for the engine's context window, oversized
message contents are summarized with the LOCAL LLM first, and only the
summary (+ untouched small messages) reaches the primary engine.

Fail-safe: any error returns the original messages unchanged, so the
request behaves exactly as if compression did not exist.

Thresholds are per-engine (the caller passes the right one):
- 100000 est. tokens for the remote engine (Groq-class, ~128K window)
- 12000 est. tokens for the local engine (llama-server -c 16384)
The estimator is deliberately conservative (3 chars/token) for
Arabic-heavy text, so real usage stays comfortably below each window.
"""

EST_CHARS_PER_TOKEN = 3        # conservative for Arabic-heavy text
COMPRESS_THRESHOLD_TOKENS = 12000
PER_MESSAGE_TOKENS = 4000
CHUNK_CHARS = 6000
SUMMARY_SYSTEM = "انت ملخص دقيق وموجز. لخص ما يصلك مع الاحتفاظ بالنقاط والمعلومات المهمة فقط."
SUMMARY_PREFIX = "لخص النص التالي بايجاز:\n\n"
AUTO_NOTE = "[ملخص تلقائي لتقليل التوكنز - النص الاصلي تجاوز عتبة السياق]\n"


def estimate_tokens(text):
    if not text:
        return 0
    return len(text) // EST_CHARS_PER_TOKEN + 1


def _content_text(msg):
    if isinstance(msg, dict):
        c = msg.get("content", "")
        return c if isinstance(c, str) else str(c)
    return str(msg)


def _chunks(text, size=CHUNK_CHARS):
    return [text[i:i + size] for i in range(0, len(text), size)]


def _local_text(res):
    if isinstance(res, dict):
        return str(res.get("content", "") or "")
    return str(res or "")


def _summarize(text, local_llm):
    parts = []
    genuine = 0
    for ch in _chunks(text):
        try:
            s = _local_text(local_llm.chat([
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": SUMMARY_PREFIX + ch},
            ])).strip()
        except Exception:
            s = ""
        if not s or s.startswith("\u274c"):
            parts.append(ch[:2000])  # degraded chunk: truncated original
        else:
            genuine += 1
            parts.append(s)
    if genuine == 0:
        # Local summarizer is dead: do NOT mutilate the text.
        # The primary engine decides (Groq has a large window;
        # the local engine fails honestly as it would anyway).
        return text
    return AUTO_NOTE + "\n".join(parts)


def maybe_compress_messages(messages, local_llm, threshold=COMPRESS_THRESHOLD_TOKENS):
    """Return messages with oversized contents summarized. Never raises."""
    try:
        if not messages or local_llm is None:
            return messages
        total = sum(estimate_tokens(_content_text(m)) for m in messages)
        if total <= threshold:
            return messages
        out = []
        for m in messages:
            if isinstance(m, dict) and estimate_tokens(_content_text(m)) > PER_MESSAGE_TOKENS:
                m = dict(m)
                m["content"] = _summarize(_content_text(m), local_llm)
            out.append(m)
        return out
    except Exception:
        return messages
