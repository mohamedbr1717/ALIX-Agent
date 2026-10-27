"""Shared helpers for the planning use cases.

Time, ids, argument hashing and — most importantly — the stored
text discipline of spec §9.3: result summaries kept in
plans.json are truncated to <= 500 chars and secret-redacted
before storage; raw tool results are NEVER persisted.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime

from domain.planning.entities import MAX_STORED_TEXT_CHARS

#: Conservative secret shapes (same spirit as the LLM router's
#: sensitivity patterns and memory's redaction): redact the value,
#: keep the surrounding text readable.
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{8,}"),
    re.compile(
        r"(?i)(api[_-]?key|password|passwd|secret|token)"
        r"(\s*[:=]\s*)(\S+)"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def system_clock() -> datetime:
    """Default clock: local time with offset."""
    return datetime.now().astimezone()


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def new_plan_id(moment: datetime) -> str:
    """``p_<YYYYMMDDTHHMMSS>_<4 hex>`` (spec §2.3) — a short
    random suffix, not a sequence counter: the bot and the
    scheduler daemon never coordinate plan creation."""
    return (
        f"p_{moment.strftime('%Y%m%dT%H%M%S')}_"
        f"{secrets.token_hex(2)}"
    )


def hash_args(args: dict) -> str:
    """Stable hash of a tool-call argument dict (prior actions)."""
    try:
        payload = json.dumps(
            args, ensure_ascii=False, sort_keys=True, default=str
        )
    except (TypeError, ValueError):
        payload = repr(args)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def redact_text(text: str) -> str:
    out = text or ""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            out = pattern.sub(
                lambda m: f"{m.group(1)}{m.group(2)}[محجوب]",
                out,
            )
        else:
            out = pattern.sub("[محجوب]", out)
    return out


def truncate_stored(text: str) -> str:
    """Redact, then truncate to the stored-text cap."""
    cleaned = redact_text(text or "").strip()
    if len(cleaned) > MAX_STORED_TEXT_CHARS:
        cleaned = cleaned[:MAX_STORED_TEXT_CHARS]
    return cleaned


def summarize_result(result: dict) -> str:
    """A one-line, storage-safe summary of a tool result dict."""
    if not isinstance(result, dict):
        return truncate_stored(str(result))
    text = (
        result.get("message")
        or result.get("stdout")
        or result.get("error")
        or ""
    )
    return truncate_stored(str(text))


def result_error_text(result: dict) -> str:
    """The failure text stored on a FAILED step (truncated)."""
    if not isinstance(result, dict):
        return truncate_stored(str(result))
    text = (
        result.get("error")
        or result.get("message")
        or "فشلت الأداة دون رسالة."
    )
    return truncate_stored(str(text))
