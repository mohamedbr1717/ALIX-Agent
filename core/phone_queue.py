"""ALIX phone queue — VPS↔phone bridge for calls/SMS.

VPS side: ALIX enqueues requests when Termux:API is unavailable.
Phone side: poller script (Termux) picks up requests via SSH,
prompts for explicit approval, executes via Termux:API.

Queue layout (under ALIX-Agent/phone_queue/):
    requests/<id>.json  — pending requests
    results/<id>.json   — completed results
    archive/            — processed requests

Request format:
    {"id": "...", "type": "call"|"sms", "number": "...",
     "message": "...",  # sms only
     "created": "ISO8601", "status": "pending"}

Result format:
    {"id": "...", "status": "approved"|"denied"|"failed"|"done",
     "detail": "...", "completed": "ISO8601"}
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _queue_base() -> Path:
    # Resolved relative to this file's repo root
    here = Path(__file__).resolve()
    # core/phone_queue.py -> repo root
    root = here.parent.parent
    q = root / "phone_queue"
    (q / "requests").mkdir(parents=True, exist_ok=True)
    (q / "results").mkdir(parents=True, exist_ok=True)
    (q / "archive").mkdir(parents=True, exist_ok=True)
    return q


def enqueue_request(
    req_type: str,
    number: str,
    message: str = "",
) -> dict:
    """Write a phone request to the queue. Returns the request dict."""
    q = _queue_base()
    rid = uuid.uuid4().hex[:12]
    req = {
        "id": rid,
        "type": req_type,  # "call" | "sms"
        "number": number,
        "message": message,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    path = q / "requests" / f"{rid}.json"
    # Atomic write
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(path)
    return req


def list_pending() -> list[dict]:
    """List all pending requests (for the phone poller)."""
    q = _queue_base()
    out = []
    for p in sorted((q / "requests").glob("*.json")):
        try:
            req = json.loads(p.read_text(encoding="utf-8"))
            if req.get("status") == "pending":
                out.append(req)
        except Exception:
            continue
    return out


def complete_request(rid: str, status: str, detail: str = "") -> None:
    """Mark a request done and archive it. Called by phone poller."""
    q = _queue_base()
    src = q / "requests" / f"{rid}.json"
    if not src.exists():
        return
    req = json.loads(src.read_text(encoding="utf-8"))
    result = {
        "id": rid,
        "status": status,  # approved|denied|failed|done
        "detail": detail,
        "completed": datetime.now(timezone.utc).isoformat(),
        "request": req,
    }
    (q / "results" / f"{rid}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Archive the request
    src.rename(q / "archive" / f"{rid}.json")


def get_result(rid: str, timeout_s: int = 0) -> dict | None:
    """Poll for a result (VPS side, optional blocking)."""
    import time
    q = _queue_base()
    deadline = time.time() + timeout_s
    while True:
        p = q / "results" / f"{rid}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        if time.time() >= deadline:
            return None
        time.sleep(2)
