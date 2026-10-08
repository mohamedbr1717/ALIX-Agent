"""Unified secret scrubbing — single source of truth.

Consolidates three previously scattered mechanisms (point 10):
- regex patterns over text (was core/memory.py::_SECRET_PATTERNS)
- key-name based redaction, recursive (was core/observability.py)
- literal secret replacement (was core/llm.py error redaction)

Behavior is preserved except for one deliberate tightening: observability
values now also get regex pattern scrubbing (previously a sk-... value
under a non-sensitive key name passed through audit logs unredacted —
flagged in the 2026-10-08 audit). Only the location is unified so a new
secret shape requires one edit, not three.
"""

from __future__ import annotations

import re
from typing import Any

# ------------------------------------------------------------------
# 1. Regex patterns over free text (high-confidence shapes)
# ------------------------------------------------------------------

SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    # AWS access key IDs
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    # OpenAI / Anthropic / generic vendor "sk-..." style keys
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    # GitHub tokens
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # PEM-style private key blocks
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # Bearer <token> JWT-style tokens
    (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b"), "Bearer [REDACTED_TOKEN]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "[REDACTED_JWT]",
    ),
    # key/secret/password/token = value assignments (common in
    # .env-style pasted config)
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9/+._-]{8,}['\"]?"
        ),
        r"\1=[REDACTED]",
    ),
]


def scrub_text(text: str) -> str:
    """Apply regex secret patterns to free text. Best-effort, not a guarantee."""
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ------------------------------------------------------------------
# 2. Key-name based redaction, recursive over nested structures
# ------------------------------------------------------------------

SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    }
)


def _key_is_sensitive(key: str) -> bool:
    return key.lower().replace("-", "_") in SENSITIVE_KEYS


def scrub_value(
    value: Any,
    *,
    key: str | None = None,
    max_value_length: int = 2000,
) -> Any:
    """Recursively sanitize a value; redact whole value when its key is sensitive."""
    if key is not None and _key_is_sensitive(key):
        return "[REDACTED]"

    if isinstance(value, dict):
        return {str(k): scrub_value(v, key=str(k),
                                    max_value_length=max_value_length)
                for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [scrub_value(item, max_value_length=max_value_length)
                for item in value]

    if isinstance(value, str):
        if len(value) > max_value_length:
            return value[:max_value_length] + "...[TRUNCATED]"
        return scrub_text(value)

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return scrub_text(str(value))


# ------------------------------------------------------------------
# 3. Literal secret replacement (known secret values)
# ------------------------------------------------------------------

def scrub_literal(text: str, secrets: list[str],
                  marker: str = "***REDACTED***") -> str:
    """Replace known secret values verbatim (e.g. the configured API key)."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, marker)
    return text
