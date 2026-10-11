#!/usr/bin/env python3
"""Self-improvement slice 2: draft fix proposals + approval gate.

Reads the machine-readable diagnosis (diagnosis/latest.json, written by
self_diagnose.py), turns each new signal into a concrete fix proposal
(proposals/<id>.md), and routes it through the EXISTING scheduled-approval
machinery (core/scheduled_approval.request_approval):

  - tool_name="proposal", task_name="🔧 اقتراح إصلاح ذاتي", level="proposal"
  - the Telegram bot shows the card; 180s TTL; نعم/لا.
  - verdicts are reconciled here: approved -> ready for slice 3 (apply);
    denied -> never re-proposed; expired -> re-proposable next cycle.

Nothing is executed here and nothing self-modifies: a "نعم" only authorizes
drafting+applying the fix with tests (slice 3 / supervised). Any failure
degrades to a note; exit code is always 0.

Usage:
    python3 scripts/draft_proposals.py [--dry-run] [--no-wait]
    python3 scripts/draft_proposals.py --diagnosis PATH --proposals-dir DIR --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
try:
    from core import scheduled_approval as sa
except Exception as exc:  # pragma: no cover - degraded below
    sa = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

HOME = Path.home()
DIAGNOSIS_FILE = HOME / "ALIX-Agent" / "diagnosis" / "latest.json"
PROPOSALS_DIR = HOME / "ALIX-Agent" / "proposals"
INDEX_FILE = PROPOSALS_DIR / "index.json"
OUTBOX_DIR = HOME / "ALIX-Agent" / "pending_approvals" / "outbox"

WAIT_BUDGET_S = 200  # total seconds to wait for card verdicts
OPEN_STATUSES = {"proposed", "approved"}


def fingerprint(signal: dict) -> str:
    key = f"{signal.get('type', '?')}:{signal.get('tool', '?')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def load_index() -> dict:
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


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


def _short_list(items: list[str], n: int = 3) -> str:
    items = [i for i in items if i][:n]
    if not items:
        return "—"
    return "\n".join(f"- {i[:100]}" for i in items)


def build_proposal(signal: dict, days: int) -> tuple[str, str, str, str]:
    """Return (proposal_id, title, card_summary, body_md)."""
    pid = uuid.uuid4().hex[:12]
    date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    stype = signal.get("type", "?")
    tool = signal.get("tool", "?")

    if stype == "tool_failures":
        fails = signal.get("failures", 0)
        calls = signal.get("calls", 0)
        title = f"تحقيق في إخفاقات {tool}"
        summary = f"{tool}: {fails} إخفاقات من {calls} استدعاءات (آخر {days} أيام)"
        body = f"""# اقتراح إصلاح: {title}
- المعرف: {pid} | التاريخ: {date} | الحالة: proposed

## الإشارة
الأداة `{tool}` أخفقت **{fails}** مرات من أصل **{calls}** استدعاءات خلال آخر {days} أيام.
أحدث ملخصات الإخفاق:
{_short_list(signal.get("summaries", []))}

## فرضيات الأسباب
- معالجة ناقصة لحالة حدّية (مثال: عنصر غير موجود).
- وسائط خاطئة تُمرَّر للأداة من الطبقة العليا.
- اعتماد خارجي متقطع (شبكة / API).

## الإصلاح المقترح
1. فحص السجل الكامل لإخفاقات الأداة وتحديد النمط.
2. إضافة معالجة صريحة للحالة الفاشلة (fail-closed، لا تخمين).
3. اختبار سلوكي يعيد إنتاج الإخفاق ثم يثبت الإصلاح.

## خطة التحقق
- الاختبارات السلوكية ذات الصلة خضراء.
- تشخيص الأسبوع التالي: صفر إخفاقات جديدة للأداة.

## المخاطر
منخفضة — التحقيق قراءة أولًا؛ أي تعديل كود يُراجَع قبل التطبيق.
"""
    elif stype == "denied":
        count = signal.get("count", 0)
        title = f"مراجعة رفض {tool}"
        summary = f"محمد رفض {tool} {count} مرات (آخر {days} أيام)"
        body = f"""# اقتراح إصلاح: {title}
- المعرف: {pid} | التاريخ: {date} | الحالة: proposed

## الإشارة
رفض محمد بطاقات الموافقة للأداة `{tool}` **{count}** مرات خلال آخر {days} أيام.

## فرضيات الأسباب
- الأداة تُقترَح في سياق لا يريد فيه محمد أتمتتها.
- وصف الأداة أو توقيت اقتراحها مضلِّل.

## الإصلاح المقترح
1. مراجعة المواضع التي يُقترَح فيها استدعاء الأداة.
2. تضييق شروط الاقتراح/التنفيذ في الـpolicy أو الوصف.
3. إن كان الرفض مبدئيًا: توثيق ذلك وإيقاف الاقتراح نهائيًا.

## خطة التحقق
- أسبوع تشخيص تالٍ دون رفض جديد للأداة (أو قرار مبدئي موثق).

## المخاطر
منخفضة — تغيير سلوكي في الاقتراح فقط، لا يمس التنفيذ.
"""
    else:  # undone
        count = signal.get("count", 0)
        title = f"مراجعة سلوك {tool} (إجراءات معكوسة)"
        summary = f"محمد عكس {tool} {count} مرات (آخر {days} أيام)"
        body = f"""# اقتراح إصلاح: {title}
- المعرف: {pid} | التاريخ: {date} | الحالة: proposed

## الإشارة
عكس محمد (undo) إجراءات نفذتها الأداة `{tool}` **{count}** مرات خلال آخر {days} أيام —
مؤشر على سلوك خاطئ متكرر.

## فرضيات الأسباب
- الأداة تنفذ افتراضًا لم يقصده محمد.
- تحقق ناقص قبل التنفيذ.

## الإصلاح المقترح
1. فحص الإجراءات المعكوسة وتحديد النمط المشترك.
2. إضافة خطوة تأكيد/تحقق قبل تنفيذ الأداة في تلك الحالات.
3. اختبار سلوكي يغطي النمط.

## خطة التحقق
- الاختبارات خضراء + أسبوع دون عكس جديد.

## المخاطر
منخفضة — تحقيق وتضييق سلوكي، لا توسيع صلاحيات.
"""
    body += "\n---\nالموافقة على البطاقة = الإذن بتنفيذ هذا الإصلاح (صياغة + تطبيق + اختبار) ثم تقرير.\n"
    return pid, title, summary, body


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


def main() -> int:
    global PROPOSALS_DIR, INDEX_FILE, OUTBOX_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnosis", type=Path, default=DIAGNOSIS_FILE)
    ap.add_argument("--proposals-dir", type=Path, default=PROPOSALS_DIR)
    ap.add_argument("--outbox", type=Path, default=OUTBOX_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
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
    try:
        diag = json.loads(args.diagnosis.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        print("no diagnosis file; nothing to propose")
        return 0
    signals = diag.get("signals", []) or []
    days = diag.get("window_days", 7)
    if not signals:
        print("no signals; nothing to propose")
        return 0
    if sa is None:
        print(f"approval machinery unavailable ({_IMPORT_ERROR}); skipped")
        return 0

    index = load_index()
    queued: list[tuple[str, str, str]] = []  # (request_id, proposal_id, fingerprint)

    for signal in signals:
        fp = fingerprint(signal)
        status = index.get(fp, {}).get("status")
        if status in OPEN_STATUSES or status == "denied":
            continue  # already open, approved, or explicitly denied: never re-ask
        pid, title, summary, body = build_proposal(signal, days)
        if args.dry_run:
            print(f"--- PROPOSAL {pid} [{fp}] ---")
            print(f"title: {title}")
            print(f"card: {summary}")
            print(body[:400] + "…")
            continue
        PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        (PROPOSALS_DIR / f"{pid}.md").write_text(body, encoding="utf-8")
        try:
            req = sa.request_approval(
                task_id=None,
                task_name="🔧 اقتراح إصلاح ذاتي",
                tool_name="proposal",
                arguments={
                    "proposal_id": pid,
                    "title": title,
                    "summary": summary,
                },
                level="proposal",
            )
        except Exception as exc:
            print(f"queue failed for {pid}: {type(exc).__name__}", file=sys.stderr)
            continue
        index[fp] = {
            "proposal_id": pid,
            "title": title,
            "status": "proposed",
            "request_id": req["id"],
            "created": datetime.now(timezone.utc).isoformat(),
        }
        queued.append((req["id"], pid, fp))
    if args.dry_run:
        print(f"queued {len(queued)} proposal(s)")
        return 0
    save_index(index)

    if not queued:
        print("queued 0 proposal(s)")
        return 0
    if args.no_wait:
        print(f"queued {len(queued)} proposal(s); not waiting")
        return 0

    # Wait for verdicts (bounded), then reconcile + archive + report.
    deadline = time.time() + WAIT_BUDGET_S
    lines = ["🔧 مقترحات الإصلاح الذاتي", ""]
    for rid, pid, fp in queued:
        remaining = deadline - time.time()
        verdict = None
        if remaining > 0:
            try:
                verdict = sa.await_verdict(rid, timeout_s=min(remaining, 185))
            except Exception:
                verdict = None
        if verdict and verdict.get("approved"):
            status, reason = "approved", "user approved"
            mark = "✅"
        elif verdict and not verdict.get("approved"):
            status, reason = "denied", "user denied"
            mark = "❌"
        else:
            status, reason = "expired", "no verdict in 180s"
            mark = "⏳"
        try:
            sa.complete_request(rid, status, reason)
        except Exception:
            pass
        entry = index.get(fp, {})
        entry["status"] = status
        entry["decided_at"] = datetime.now(timezone.utc).isoformat()
        if status == "expired":
            # Expired (not denied): allow re-proposal next cycle.
            index.pop(fp, None)
        else:
            index[fp] = entry
        title = entry.get("title", pid)
        lines.append(f"{mark} {title}: {status}")
    save_index(index)

    lines += [
        "",
        "المقبول → يُنفَّذ في الشريحة 3 (صياغة + تطبيق + اختبار) ثم تقرير.",
        "المرفوض → أُغلق نهائيًا ولن يُعاد طرحه.",
        "المنتهي → سيُعاد طرحه الأسبوع المقبل إن استمرت الإشارة.",
    ]
    queue_report("\n".join(lines), OUTBOX_DIR)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
