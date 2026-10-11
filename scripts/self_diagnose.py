#!/usr/bin/env python3
"""ALIX self-diagnosis — slice 1 (read-only).

Weekly read-only scan of the agent's own traces:
  - history/actions.jsonl  (tool calls with ok/failure + undone flags)
  - pending_approvals/archive/*.json  (approved / denied / expired cards)

It computes deterministic signals (no LLM, no changes) and delivers a short
Arabic report through the scheduler outbox (pending_approvals/outbox/*.json),
which the Telegram bot poller forwards. Never modifies anything, never fails
the cron: any problem degrades to a "no data" report.

Usage:
    python3 scripts/self_diagnose.py [--days 7] [--dry-run]
    python3 scripts/self_diagnose.py --history PATH --archive DIR --outbox DIR --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
HISTORY_FILE = HOME / "ALIX-Agent" / "history" / "actions.jsonl"
ARCHIVE_DIR = HOME / "ALIX-Agent" / "pending_approvals" / "archive"
OUTBOX_DIR = HOME / "ALIX-Agent" / "pending_approvals" / "outbox"

# Signal thresholds.
FLAG_MIN_FAILURES = 3      # absolute failures -> red flag
FLAG_MIN_CALLS = 5         # minimum calls for rate-based flag
FLAG_FAIL_RATE = 0.30      # failure rate -> red flag (with FLAG_MIN_CALLS)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError):
        return None


def load_actions(path: Path, since: datetime) -> list[dict]:
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None or ts < since:
            continue
        records.append(rec)
    return records


def load_archive(path: Path, since: datetime) -> list[dict]:
    records = []
    try:
        files = sorted(path.glob("*.json"))
    except OSError:
        return []
    for fp in files:
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            continue
        ts = _parse_ts(rec.get("completed_at") or rec.get("expired_at") or rec.get("created"))
        if ts is None or ts < since:
            continue
        records.append(rec)
    return records


def analyze_actions(records: list[dict]) -> dict:
    total = len(records)
    failed = [r for r in records if not r.get("ok", False)]
    undone = [r for r in records if r.get("undone")]
    per_tool_calls: Counter = Counter()
    per_tool_fails: Counter = Counter()
    for r in records:
        name = r.get("tool_name", "?") or "?"
        per_tool_calls[name] += 1
        if not r.get("ok", False):
            per_tool_fails[name] += 1
    flags = []
    for name, calls in per_tool_calls.most_common():
        fails = per_tool_fails.get(name, 0)
        if fails >= FLAG_MIN_FAILURES or (
            calls >= FLAG_MIN_CALLS and fails / calls >= FLAG_FAIL_RATE
        ):
            flags.append((name, fails, calls))
    recent_failures = [
        (r.get("tool_name", "?"), r.get("summary", "") or "")
        for r in failed[-5:]
    ][::-1]
    return {
        "total": total,
        "failed": len(failed),
        "undone": len(undone),
        "undone_tools": Counter(
            r.get("tool_name", "?") for r in undone
        ).most_common(3),
        "flags": flags,
        "recent_failures": recent_failures,
    }


def analyze_archive(records: list[dict]) -> dict:
    by_status: Counter = Counter()
    denied_tools: Counter = Counter()
    for r in records:
        status = (r.get("status") or "unknown").lower()
        by_status[status] += 1
        if status == "denied":
            tool = r.get("tool_name") or r.get("tool") or "?"
            denied_tools[tool] += 1
    return {
        "approved": by_status.get("approved", 0),
        "denied": by_status.get("denied", 0),
        "expired": by_status.get("expired", 0),
        "denied_tools": denied_tools.most_common(3),
    }


def build_report(a: dict, arch: dict, days: int, since: datetime) -> str:
    now = datetime.now(timezone.utc).astimezone()
    since_l = since.astimezone()
    L = []
    L.append("🔍 التشخيص الذاتي الأسبوعي")
    L.append(
        f"{since_l.strftime('%Y-%m-%d')} ← {now.strftime('%Y-%m-%d')} (آخر {days} أيام)"
    )
    L.append("")
    if a["total"] == 0 and (arch["approved"] + arch["denied"] + arch["expired"]) == 0:
        L.append("لا بيانات في هذه الفترة — الوكيل كان هادئًا.")
        L.append("")
        L.append("(الشريحة 1: تشخيص فقط — لا اقتراحات ولا تعديلات.)")
        return "\n".join(L)

    fail_rate = (a["failed"] / a["total"] * 100) if a["total"] else 0
    L.append(
        f"📊 النشاط: {a['total']} استدعاء أداة، {a['failed']} إخفاقات ({fail_rate:.0f}%)"
    )
    if a["undone"]:
        tools = ", ".join(f"{t}×{c}" for t, c in a["undone_tools"])
        L.append(f"↩️ إجراءات عكسها محمد: {a['undone']} ({tools})")
    cards_total = arch["approved"] + arch["denied"] + arch["expired"]
    if cards_total:
        L.append(
            f"🗳️ بطاقات الموافقة: {arch['approved']} قُبِلت، "
            f"{arch['denied']} رُفِضت، {arch['expired']} انتهت"
        )
    signals = []
    for name, fails, calls in a["flags"]:
        signals.append(f"🔴 {name}: {fails} إخفاقات من {calls} استدعاءات")
    for tool, cnt in arch["denied_tools"]:
        signals.append(f"🟡 رفض محمد {tool} {cnt} مرات")
    for tool, cnt in a["undone_tools"]:
        if cnt >= 2:
            signals.append(f"🟡 عكس محمد {tool} {cnt} مرات (ربما سلوك خاطئ متكرر)")
    L.append("")
    if signals:
        L.append("إشارات تستحق النظر:")
        L.extend(f"- {s}" for s in signals[:8])
    else:
        L.append("لا إشارات حمراء هذا الأسبوع ✅")
    if a["recent_failures"]:
        L.append("")
        L.append("أحدث الإخفاقات:")
        for tool, summary in a["recent_failures"][:5]:
            short = (summary[:80] + "…") if len(summary) > 80 else summary
            L.append(f"- {tool}: {short}" if short else f"- {tool}")
    L.append("")
    L.append("(الشريحة 1: تشخيص فقط — لا اقتراحات ولا تعديلات.)")
    return "\n".join(L)


def queue_report(text: str, outbox: Path) -> None:
    outbox.mkdir(parents=True, exist_ok=True)
    nid = uuid.uuid4().hex[:12]
    msg = {
        "id": nid,
        "text": text,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    tmp = outbox / f"{nid}.tmp"
    tmp.write_text(json.dumps(msg, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, outbox / f"{nid}.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--history", type=Path, default=HISTORY_FILE)
    ap.add_argument("--archive", type=Path, default=ARCHIVE_DIR)
    ap.add_argument("--outbox", type=Path, default=OUTBOX_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, args.days))
        actions = load_actions(args.history, since)
        archive = load_archive(args.archive, since)
        report = build_report(
            analyze_actions(actions), analyze_archive(archive), args.days, since
        )
        if args.dry_run:
            print(report)
        else:
            queue_report(report, args.outbox)
            print("report queued")
    except Exception as exc:  # never fail the cron; degrade to a note
        try:
            fallback = (
                "🔍 التشخيص الذاتي: تعذّر إكمال الفحص "
                f"({type(exc).__name__}) — لا بيانات هذا الأسبوع."
            )
            if args.dry_run:
                print(fallback)
            else:
                queue_report(fallback, args.outbox)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
