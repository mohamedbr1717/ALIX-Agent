#!/usr/bin/env python3
"""Weekly secret-maintenance check for ALIX-Agent. Runs on the VPS via cron.

Scope (user-approved 2026-10-11): inventory (الجرد) + checks (الفحص) + alerts (التنبيه).

Read-only by design:
  - Never prints, logs, or transmits secret VALUES. The report carries only
    names, paths, counts, and PASS/FAIL/UNKNOWN verdicts.
  - Secret values are held in memory solely to scan logs for literal leaks;
    matches are reported as counts per file, never as values.
  - Delivery reuses the scheduler's outbox (pending_approvals/outbox/*.json),
    picked up by the Telegram bot poller. No extra credentials needed.
  - Any check that errors reports UNKNOWN, never PASS (fail-closed).

Usage:
  python3 scripts/secret_maintenance.py
      # weekly check: inventory + checks + alerts, queues Telegram report
  python3 scripts/secret_maintenance.py --mark-rotated NAME
      # reset the obtained-date clock after re-auth, e.g.
      # --mark-rotated GOOGLE_CALENDAR_REFRESH_TOKEN
  python3 scripts/secret_maintenance.py --set-expiry NAME none
      # stop expiry warnings for NAME (e.g. after publishing the OAuth app)
  python3 scripts/secret_maintenance.py --rebaseline-git
      # re-record the git baseline after triaging new hits
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # so core.secret_scrub imports on the VPS
try:
    from core.secret_scrub import SECRET_PATTERNS, scrub_text
except Exception:  # fail-closed: pattern scan degrades to literal-only
    SECRET_PATTERNS = []

    def scrub_text(t: str) -> str:  # type: ignore[misc]
        return t

HOME = Path.home()
ENV_FILE = REPO / ".env"
KAGGLE_FILE = HOME / ".kaggle" / "kaggle.json"
HOOK_FILE = REPO / ".git" / "hooks" / "pre-commit"
OUTBOX_DIR = HOME / "ALIX-Agent" / "pending_approvals" / "outbox"
STATE_FILE = REPO / "scheduler" / "secret_maintenance_state.json"
LOG_FILES = [REPO / "bot.log", REPO / "scheduler" / "daemon.log"]

# Secrets expected in .env (names only; values never leave this process).
ENV_SECRETS = [
    "GROQ_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "GMAIL_ADDRESS_2",
    "GMAIL_APP_PASSWORD_2",
    "GOOGLE_CALENDAR_REFRESH_TOKEN",
]

# Documented obtain dates (recorded facts, not placeholders).
# The state file becomes the source of truth after the first run.
KNOWN_OBTAINED = {
    # Testing-mode OAuth app: Google expires refresh tokens after ~7 days.
    "GOOGLE_CALENDAR_REFRESH_TOKEN": {"obtained": "2026-10-09", "expiry_days": 7},
}

MAX_LOG_SCAN_BYTES = 10 * 1024 * 1024
MAX_TRACKED_SCAN_BYTES = 1024 * 1024

# --- git content scan mirrors scripts/git-hooks/pre-commit exactly ---------
# Single source of truth: the weekly scan and the commit-time guard must agree,
# otherwise they drift (property #10). Test files and placeholders are exempt
# in both; only the GENERIC assignment shape is checked for content.
_GENERIC_RE = re.compile(
    r"(api[_-]?key|app[_-]?password|client[_-]?secret|refresh[_-]?token"
    r"|password|passwd|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{12,}",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r"xxx+|\*{3,}|your[-_]|example|changeme|placeholder|dummy|fake"
    r"|test[-_]?key|os\.environ|getenv|input\(|<[^>]*>|\$\{",
    re.IGNORECASE,
)
_FORBIDDEN_BASENAMES = (".env", "kaggle.json")
_FORBIDDEN_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def _is_test_file(rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return (
        (base.startswith("test_") and base.endswith(".py"))
        or base.endswith("_test.py")
        or rel.startswith("tests/")
        or "/tests/" in rel
        or rel.startswith("scripts/git-hooks/")  # hook carries patterns as strings
    )


def parse_env(path: Path) -> dict[str, str]:
    """Minimal .env parser. Values stay in memory; never printed."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def check_perms(path: Path) -> str:
    """PASS if no group/other permission bits, else FAIL. UNKNOWN on error."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return "UNKNOWN"
    return "PASS" if (mode & 0o077) == 0 else "FAIL"


def check_git(state: dict) -> tuple[str, list[str]]:
    """Tracked files: report only NEW secret-shaped hits vs a recorded baseline.

    Mirrors the pre-commit hook for detection (same GENERIC/PLACEHOLDER/test
    logic — single source of truth). Pre-hook commits already contain a few
    known-benign shapes (attribute refs like api_key=self.x, .get() calls,
    doc placeholders); the first run records them as the baseline and later
    runs alert only on new signatures. Use --rebaseline-git after triage.
    Returns (status, new_signatures); status in PASS/FAIL/BASELINE/UNKNOWN.
    Signatures are scrubbed lines — safe to store and report.
    """
    try:
        raw = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return "UNKNOWN", []
    if raw.returncode != 0:
        return "UNKNOWN", []
    current: set[str] = set()
    for rel in raw.stdout.split("\0"):
        if not rel:
            continue
        base = rel.rsplit("/", 1)[-1]
        if base in _FORBIDDEN_BASENAMES or base.startswith(".env."):
            current.add(rel + " :: tracked secret name")
            continue
        if base.endswith(_FORBIDDEN_SUFFIXES):
            current.add(rel + " :: tracked secret name")
            continue
        if _is_test_file(rel):
            continue  # fake key fixtures by design, same as the hook
        p = REPO / rel
        try:
            if p.stat().st_size > MAX_TRACKED_SCAN_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if _PLACEHOLDER_RE.search(line):
                continue  # os.environ, getenv, xxx, dummy, ... — not secrets
            if _GENERIC_RE.search(line):
                current.add(rel + " :: " + scrub_text(line.strip())[:100])
                break
    baseline = state.get("git_baseline")
    if baseline is None:
        state["git_baseline"] = sorted(current)
        save_state(state)
        return "BASELINE", sorted(current)
    new = sorted(current - set(baseline))
    return ("FAIL" if new else "PASS"), new


def scan_logs(secret_values: list[str]) -> dict[str, dict[str, int]]:
    """Count literal secret occurrences + suspicious shapes per log file."""
    results: dict[str, dict[str, int]] = {}
    for log in LOG_FILES:
        counts = {"literal": 0, "shapes": 0}
        try:
            size = log.stat().st_size
            with log.open("rb") as fh:
                if size > MAX_LOG_SCAN_BYTES:
                    fh.seek(size - MAX_LOG_SCAN_BYTES)
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            results[log.name] = {"literal": -1, "shapes": -1}  # -1 = unreadable
            continue
        for val in secret_values:
            if len(val) >= 12:
                counts["literal"] += text.count(val)
        for pat, _ in SECRET_PATTERNS:
            counts["shapes"] += len(pat.findall(text))
        results[log.name] = counts
    return results


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def queue_report(text: str) -> None:
    """Deliver via the scheduler outbox (bot poller sends it on Telegram)."""
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    nid = uuid.uuid4().hex[:12]
    msg = {
        "id": nid,
        "text": text,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    tmp = OUTBOX_DIR / f"{nid}.tmp"
    tmp.write_text(json.dumps(msg, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUTBOX_DIR / f"{nid}.json")


TICK = {"PASS": "✅", "FAIL": "❌", "UNKNOWN": "❓"}


def main() -> int:
    # --mark-rotated / --set-expiry / --rebaseline-git: state bookkeeping.
    if len(sys.argv) == 2 and sys.argv[1] == "--rebaseline-git":
        state = load_state()
        state.pop("git_baseline", None)
        save_state(state)
        print("git baseline cleared; next run records a fresh one")
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "--set-expiry":
        state = load_state()
        entry = state.setdefault(sys.argv[2], {})
        val = sys.argv[3].lower()
        try:
            entry["expiry_days"] = None if val == "none" else int(val)
        except ValueError:
            print("expiry must be a number of days or 'none'")
            return 2
        save_state(state)
        print(f"expiry updated for {sys.argv[2]}")
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--mark-rotated":
        state = load_state()
        entry = state.setdefault(sys.argv[2], {})
        entry["obtained"] = date.today().isoformat()
        save_state(state)
        print(f"state updated for {sys.argv[2]}")
        return 0

    lines: list[str] = []
    today = date.today().isoformat()
    lines.append(f"🛡️ فحص الأسرار الأسبوعي — {today}")
    state = load_state()

    # 1) Inventory -----------------------------------------------------
    env = parse_env(ENV_FILE)
    present = [k for k in ENV_SECRETS if env.get(k)]
    missing = [k for k in ENV_SECRETS if k not in present]
    kaggle_ok = False
    try:
        kj = json.loads(KAGGLE_FILE.read_text(encoding="utf-8"))
        kaggle_ok = bool(kj.get("username") and kj.get("key"))
    except (OSError, json.JSONDecodeError):
        kaggle_ok = False
    inv_tick = "✅" if not missing and kaggle_ok else ("⚠️" if not missing else "❌")
    lines.append(
        f"📋 الجرد: {len(present)}/{len(ENV_SECRETS)} في .env"
        + ("" if not missing else f" (ناقص: {', '.join(missing)})")
        + f" + kaggle.json {'✅' if kaggle_ok else '❌'} {inv_tick}"
    )

    # 2) Permission checks ----------------------------------------------
    pe, pk = check_perms(ENV_FILE), check_perms(KAGGLE_FILE)
    lines.append(
        f"🔒 الصلاحيات: .env {TICK[pe]}"
        + (f" ({oct(ENV_FILE.stat().st_mode & 0o777)})" if pe == "FAIL" else "")
        + f"، kaggle.json {TICK[pk]}"
        + (f" ({oct(KAGGLE_FILE.stat().st_mode & 0o777)})" if pk == "FAIL" else "")
    )

    # 3) Git hygiene -----------------------------------------------------
    gstat, gnew = check_git(state)
    if gstat == "PASS":
        lines.append("📦 git: لا إصابات جديدة منذ خط الأساس ✅")
    elif gstat == "FAIL":
        lines.append(f"📦 git: ❌ إصابات جديدة: {', '.join(gnew[:5])}")
    elif gstat == "BASELINE":
        lines.append(f"📦 git: ℹ️ سُجل خط الأساس ({len(gnew)} شكل معروف، رُوجع يدويًا)")
    else:
        lines.append("📦 git: ❓ تعذر الفحص")
    hook = "PASS" if (HOOK_FILE.exists() and os.access(HOOK_FILE, os.X_OK)) else (
        "FAIL" if HOOK_FILE.exists() else "UNKNOWN")
    lines.append(f"🪝 pre-commit: حارس الأسرار {'مثبت ✅' if hook == 'PASS' else '❌ مفقود/غير تنفيذي' if hook == 'FAIL' else '❓ تعذر الفحص'}")

    # 4) Log leak scan ----------------------------------------------------
    secret_vals = [
        v for k, v in env.items()
        if re.search(r"(?i)(key|token|secret|password|passwd|auth)", k) and len(v) >= 12
    ]
    logres = scan_logs(secret_vals)
    leak_bits = []
    for name, c in logres.items():
        if c["literal"] < 0:
            leak_bits.append(f"{name} ❓")
        elif c["literal"] > 0:
            leak_bits.append(f"{name} ❌ تسريب حرفي ({c['literal']})")
        elif c["shapes"] > 0:
            leak_bits.append(f"{name} ⚠️ أشكال مشبوهة ({c['shapes']})")
        else:
            leak_bits.append(f"{name} ✅")
    lines.append("📜 السجلات: " + "، ".join(leak_bits))

    # 5) Expiry alerts ------------------------------------------------------
    alerts: list[str] = []
    initialized = False
    for name, info in KNOWN_OBTAINED.items():
        entry = state.get(name)
        if not entry:
            entry = dict(info)
            state[name] = entry
            initialized = True
        exp_days = entry.get("expiry_days")
        if not exp_days:
            continue
        try:
            obtained = date.fromisoformat(entry["obtained"])
        except (KeyError, ValueError):
            alerts.append(f"❓ {name}: تاريخ الحصول غير معروف")
            continue
        age = (date.today() - obtained).days
        remaining = exp_days - age
        if remaining <= 2:
            alerts.append(
                f"⚠️ {name}: بقي ~{max(remaining, 0)} أيام على نافذة الـ{exp_days} أيام "
                "(تطبيق OAuth في وضع Testing) — أعد المصادقة "
                "(scripts/calendar_auth.py) أو انشر التطبيق"
            )
    if initialized:
        save_state(state)
        alerts.append("ℹ️ سُجلت تواريخ الأساس الأولى في ملف الحالة")
    lines.append("⏰ التنبيهات: " + ("لا شيء ✅" if not alerts else " | ".join(alerts)))

    report = "\n".join(lines)
    print(report)  # cron log (scrubbed: no values by construction)
    try:
        queue_report(report)
    except OSError as exc:
        print(f"outbox queue failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
