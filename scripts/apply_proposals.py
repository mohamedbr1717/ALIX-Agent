#!/usr/bin/env python3
"""Self-improvement slice 3: apply approved proposals (supervised).

Reads proposals/index.json. For each APPROVED proposal:
  - signal gone from diagnosis/latest.json -> RESOLVED (closed without
    intervention), reported.
  - signal persists (or no fresh diagnosis) -> TICKET_READY: writes
    proposals/<id>.implement.md, a concrete implementation ticket
    (evidence, candidate files, baseline test results, acceptance
    criteria), and notifies via outbox.

For APPLIED proposals: signal gone -> VERIFIED.

Never modifies code, never commits, never pushes. The implementation
itself happens in a supervised session (the user's standing rule:
show the diff first, named-scope approval before commit). Exit code
is always 0; any failure degrades to a note.

Usage:
    python3 scripts/apply_proposals.py [--dry-run]
    python3 scripts/apply_proposals.py --mark-applied <proposal-id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REPO_ROOT = Path(__file__).resolve().parent.parent
DIAGNOSIS_FILE = HOME / "ALIX-Agent" / "diagnosis" / "latest.json"
PROPOSALS_DIR = HOME / "ALIX-Agent" / "proposals"
INDEX_FILE = PROPOSALS_DIR / "index.json"
OUTBOX_DIR = HOME / "ALIX-Agent" / "pending_approvals" / "outbox"

TERMINAL_STATUSES = {"denied", "resolved", "verified"}
TEST_TIMEOUT_S = 180


def fingerprint(signal: dict) -> str:
    key = f"{signal.get('type', '?')}:{signal.get('tool', '?')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_index(index: dict) -> None:
    try:
        PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = INDEX_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, INDEX_FILE)
    except OSError:
        pass


def queue_report(text: str, outbox: Path) -> None:
    try:
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
    except OSError:
        pass


def candidate_files(tool: str, limit: int = 8) -> list[str]:
    """Repo files mentioning the tool (read-only grep, bounded)."""
    if not tool or len(tool) > 64:
        return []
    try:
        r = subprocess.run(
            ["grep", "-rl", "--include=*.py", tool, "."],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    files = []
    for line in r.stdout.splitlines():
        p = line.strip().lstrip("./")
        if "__pycache__" in p or p.startswith("."):
            continue
        files.append(p)
        if len(files) >= limit:
            break
    return files


def baseline_tests(tool: str) -> str:
    """Run tests mentioning the tool; return a short baseline summary."""
    test_files = [f for f in candidate_files(tool, 20) if f.startswith("test")]
    if not test_files:
        test_files = [f for f in candidate_files(tool, 20) if "/test" in f]
    if not test_files:
        return "لا توجد ملفات اختبار تذكر الأداة."
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", *test_files],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return "تعذر تشغيل الاختبارات."
    tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
    verdict = "خضراء ✅" if r.returncode == 0 else f"فاشلة ❌ (exit {r.returncode})"
    return f"{verdict} — {' '.join(test_files[:4])}\n" + "\n".join(tail)


def build_ticket(pid: str, title: str, signal: dict | None, days: int) -> str:
    date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    tool = (signal or {}).get("tool", "?")
    stype = (signal or {}).get("type", "?")
    if signal and stype == "tool_failures":
        evidence = (
            f"الأداة `{tool}` أخفقت {signal.get('failures')} من "
            f"{signal.get('calls')} استدعاءات (آخر {days} أيام)."
        )
    elif signal and stype == "denied":
        evidence = f"رُفضت بطاقات `{tool}` {signal.get('count')} مرات (آخر {days} أيام)."
    elif signal and stype == "undone":
        evidence = f"عُكست إجراءات `{tool}` {signal.get('count')} مرات (آخر {days} أيام)."
    else:
        evidence = "لا تشخيص طازج متاح — راجع ملف الاقتراح الأصلي."
    files = candidate_files(tool)
    files_txt = "\n".join(f"- `{f}`" for f in files) if files else "—"
    baseline = baseline_tests(tool)
    return f"""# تذكرة تنفيذ: {title}
- الاقتراح: `proposals/{pid}.md` | الحالة: ticket_ready | التاريخ: {date}

## السياق (من التشخيص)
{evidence}

## ملفات مرشحة للفحص (بحث آلي، قراءة فقط)
{files_txt}

## خط الأساس: نتائج الاختبارات قبل التنفيذ
{baseline}

## معايير القبول
- السبب الجذري محدد بدليل من السجل، لا تخمين.
- الإصلاح fail-closed (لا يخفي الفشل ولا يوسع الصلاحيات).
- اختبار سلوكي يعيد إنتاج المشكلة قبل الإصلاح ويثبت زوالها بعده.
- تشخيص الأسبوع التالي: الإشارة مختفية.

## ملاحظة حدودية
التنفيذ في جلسة مراجعة: عرض الـdiff أولًا + موافقة بنطاق مسمى قبل أي commit،
والـpush بموافقة مستقلة. الحلقة لا تعدل الكود وحدها أبدًا.
بعد الدمج: `python3 scripts/apply_proposals.py --mark-applied {pid}`
ثم يتحقق التشخيص الأسبوعي تلقائيًا (VERIFIED عند اختفاء الإشارة).
"""


def main() -> int:
    global PROPOSALS_DIR, INDEX_FILE, OUTBOX_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnosis", type=Path, default=DIAGNOSIS_FILE)
    ap.add_argument("--proposals-dir", type=Path, default=PROPOSALS_DIR)
    ap.add_argument("--outbox", type=Path, default=OUTBOX_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mark-applied", default=None)
    args = ap.parse_args()

    PROPOSALS_DIR = args.proposals_dir
    INDEX_FILE = PROPOSALS_DIR / "index.json"
    OUTBOX_DIR = args.outbox

    try:
        return _run(args)
    except Exception as exc:  # never fail the cron
        print(f"degraded: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0


def _run(args) -> int:
    index = load_json(INDEX_FILE) or {}
    if args.mark_applied:
        return _mark_applied(index, args)

    diag = load_json(args.diagnosis) or {}
    signals = diag.get("signals", []) or []
    days = diag.get("window_days", 7)
    live_fps = {fingerprint(s) for s in signals}
    by_fp = {fingerprint(s): s for s in signals}

    lines = ["🔧 تنفيذ المقترحات المقبولة", ""]
    changed = False

    for fp, entry in list(index.items()):
        status = entry.get("status")
        pid = entry.get("proposal_id", "?")
        title = entry.get("title", pid)
        if status == "approved":
            if signals and fp not in live_fps:
                # Signal vanished on its own -> closed without intervention.
                if not args.dry_run:
                    entry["status"] = "resolved"
                    entry["decided_at"] = datetime.now(timezone.utc).isoformat()
                    changed = True
                lines.append(f"✅ {title}: أُغلق تلقائيًا (الإشارة اختفت)")
            else:
                ticket = build_ticket(pid, title, by_fp.get(fp), days)
                if not args.dry_run:
                    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
                    (PROPOSALS_DIR / f"{pid}.implement.md").write_text(
                        ticket, encoding="utf-8"
                    )
                    entry["status"] = "ticket_ready"
                    entry["decided_at"] = datetime.now(timezone.utc).isoformat()
                    changed = True
                lines.append(f"📝 {title}: تذكرة تنفيذ جاهزة (`{pid}.implement.md`)")
        elif status == "applied":
            if signals and fp not in live_fps:
                if not args.dry_run:
                    entry["status"] = "verified"
                    entry["decided_at"] = datetime.now(timezone.utc).isoformat()
                    changed = True
                lines.append(f"🎯 {title}: تم التحقق (الإشارة مختفية بعد التنفيذ)")

    if changed and not args.dry_run:
        save_index(index)

    if len(lines) > 2:
        lines += [
            "",
            "التذاكر الجاهزة تُنفَّذ في جلسة مراجعة — قل «نفذ» في الدردشة للبدء.",
            "الحلقة لا تعدل الكود ولا تدفع وحدها أبدًا.",
        ]
        text = "\n".join(lines)
        if not args.dry_run:
            queue_report(text, OUTBOX_DIR)
        print(text)
    else:
        print("no approved/applied proposals to process")
    return 0


def _mark_applied(index: dict, args) -> int:
    for fp, entry in index.items():
        if entry.get("proposal_id") == args.mark_applied:
            if not args.dry_run:
                entry["status"] = "applied"
                entry["decided_at"] = datetime.now(timezone.utc).isoformat()
                save_index(index)
            print(f"marked applied: {entry.get('title', args.mark_applied)}")
            return 0
    print(f"proposal not found: {args.mark_applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
