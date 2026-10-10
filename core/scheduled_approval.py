"""Scheduled destructive-operation approval queue (escalation path ب).

Two processes cross here:
  - scheduler_daemon.py (writes requests, blocks up to 180s awaiting a verdict)
  - telegram_bot.py    (polls requests, shows the approval card, writes verdicts,
                        polls the outbox for cancellation notifications)

Mirrors the core/phone_queue.py pattern (requests/<id>.json → results/<id>.json).

Decision (user, 2026-10-10): scheduled destructive tools are NOT hard-rejected;
they suspend for a 180-second Telegram approval window. Approval → execute.
Denial or 180s of silence → FINAL cancel (skip + history log + user notify).
A tool NEVER executes without explicit approval.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

APPROVAL_TIMEOUT_S = 180
POLL_INTERVAL_S = 2


def _queue_base() -> Path:
    q = Path.home() / "ALIX-Agent" / "pending_approvals"
    for sub in ("requests", "results", "archive", "outbox", "outbox_archive"):
        (q / sub).mkdir(parents=True, exist_ok=True)
    return q


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.rename(path)


def request_approval(
    task_id: str | None,
    task_name: str | None,
    tool_name: str,
    arguments: dict,
    level: str,
) -> dict:
    """Write an approval request. Returns the request dict."""
    q = _queue_base()
    rid = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    req = {
        "id": rid,
        "task_id": task_id,
        "task_name": task_name,
        "tool_name": tool_name,
        "arguments": arguments if isinstance(arguments, dict) else {},
        "level": level,
        "requested_at": now.isoformat(),
        "deadline": now.timestamp() + APPROVAL_TIMEOUT_S,
        "status": "pending",
    }
    _atomic_write(q / "requests" / f"{rid}.json", req)
    return req


def await_verdict(
    rid: str, timeout_s: int = APPROVAL_TIMEOUT_S
) -> dict | None:
    """Block up to timeout_s for the bot's verdict. Verdict dict or None."""
    q = _queue_base()
    deadline = time.time() + timeout_s
    while True:
        p = q / "results" / f"{rid}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        if time.time() >= deadline:
            return None
        time.sleep(POLL_INTERVAL_S)


def write_verdict(rid: str, approved: bool, detail: str = "") -> None:
    """Called by the Telegram bot when the user answers the card.

    Late verdicts (request already expired/archived) are ignored.
    """
    q = _queue_base()
    if not (q / "requests" / f"{rid}.json").exists():
        return
    _atomic_write(
        q / "results" / f"{rid}.json",
        {
            "id": rid,
            "approved": bool(approved),
            "detail": detail,
            "completed": datetime.now(timezone.utc).isoformat(),
        },
    )


def expire_request(rid: str, reason: str) -> None:
    """Archive a request as expired/cancelled. Drops any late verdict."""
    _finish_request(rid, "expired", reason, stamp_key="expired_at")


def complete_request(rid: str, status: str, reason: str = "") -> None:
    """Archive a request as finished (approved/denied) and clean up.

    Called by the daemon after consuming the verdict, so the bot stops
    re-carding an already-answered request.
    """
    _finish_request(rid, status, reason, stamp_key="completed_at")


def _finish_request(
    rid: str, status: str, reason: str, stamp_key: str
) -> None:
    q = _queue_base()
    src = q / "requests" / f"{rid}.json"
    if src.exists():
        try:
            req = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            req = {"id": rid}
        req["status"] = status
        req["reason"] = reason
        req[stamp_key] = datetime.now(timezone.utc).isoformat()
        _atomic_write(q / "archive" / f"{rid}.json", req)
        src.unlink()
    late = q / "results" / f"{rid}.json"
    if late.exists():
        late.unlink()


def list_pending() -> list[dict]:
    """Pending requests for the Telegram bot poller. Skips past-deadline ones."""
    q = _queue_base()
    now = time.time()
    out = []
    for p in sorted((q / "requests").glob("*.json")):
        try:
            req = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if req.get("status") != "pending":
            continue
        if req.get("deadline", 0) <= now:
            continue  # daemon-side expiry will archive it
        out.append(req)
    return out


def notify_user(text: str) -> dict:
    """Queue a user notification for the Telegram bot to deliver."""
    q = _queue_base()
    nid = uuid.uuid4().hex[:12]
    msg = {
        "id": nid,
        "text": text,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    _atomic_write(q / "outbox" / f"{nid}.json", msg)
    return msg


def take_notifications() -> list[dict]:
    """For the bot: pop all pending outbox notifications (archived on take)."""
    q = _queue_base()
    out = []
    for p in sorted((q / "outbox").glob("*.json")):
        try:
            msg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if msg.get("status") == "pending":
            out.append(msg)
            p.rename(q / "outbox_archive" / p.name)
    return out
