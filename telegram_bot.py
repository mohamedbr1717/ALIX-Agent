#!/usr/bin/env python3
"""ALIX Telegram bot: full remote control with human-in-the-loop approvals.

Usage (Termux):
    cd ~/ALIX-Agent
    nohup python3 telegram_bot.py > telegram/bot.log 2>&1 &

Setup (once):
    - Talk to @BotFather on Telegram, create a bot, copy the token.
    - Get your numeric Telegram ID (e.g. via @userinfobot).
    - Append to ~/ALIX-Agent/.env (gitignored, never committed):
        TELEGRAM_BOT_TOKEN=123456:ABC...
        TELEGRAM_ADMIN_ID=123456789
    - chmod 600 ~/ALIX-Agent/.env

Behavior:
    - Long-polling over stdlib urllib only (no new dependencies).
    - Admin-only: any message from another Telegram user is silently
      ignored. The token never appears in logs or messages.
    - One persistent ALIXAgent: conversation memory is kept, messages
      are handled sequentially.
    - Policy is fully enforced. Tools needing confirmation ask YOU on
      Telegram (نعم / لا), 180 s timeout -> deny (fail-closed).
    - Single instance via telegram/bot.pid; stop with: kill $(cat telegram/bot.pid)
"""
from __future__ import annotations
import traceback
from core.llm import GroqFailover

import atexit
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent),
)

from dotenv import dotenv_values  # noqa: E402

from core.agent import ALIXAgent  # noqa: E402

REPO = Path(__file__).resolve().parent
TG_DIR = REPO / "telegram"
PID_FILE = TG_DIR / "bot.pid"
LOG_PREFIX = "[telegram-bot]"

POLL_TIMEOUT = 45
CONFIRM_TIMEOUT = 180
MAX_TG_CHARS = 4000
APPROVE_WORDS = {"نعم", "موافق", "y", "yes", "ok", "تمام"}


def log(*parts) -> None:
    print(LOG_PREFIX, *parts, flush=True)


# ============================================================
# Config
# ============================================================

def load_config() -> tuple[str, int]:
    env_file = Path.home() / "ALIX-Agent" / ".env"
    file_env = dotenv_values(env_file) if env_file.is_file() else {}

    token = (
        file_env.get("TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip()
    admin_raw = (
        file_env.get("TELEGRAM_ADMIN_ID")
        or os.getenv("TELEGRAM_ADMIN_ID")
        or ""
    ).strip()

    if not token or ":" not in token:
        log("❌ TELEGRAM_BOT_TOKEN مفقود أو غير صالح في ~/.env")
        sys.exit(1)

    try:
        admin_id = int(admin_raw)
    except (TypeError, ValueError):
        log("❌ TELEGRAM_ADMIN_ID يجب أن يكون رقمًا صحيحًا.")
        sys.exit(1)

    return token, admin_id


# ============================================================
# Minimal Telegram Bot API client (stdlib only)
# ============================================================

class BotAPI:
    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}"

    def _post(self, method: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_updates(
        self, offset: int | None, timeout: int
    ) -> list[dict]:
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        url = (
            f"{self._base}/getUpdates?"
            + urllib.parse.urlencode(params)
        )
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(
                request, timeout=timeout + 15
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            log("⚠️ تعذر الوصول لتيليجرام:", exc)
            return []
        if not body.get("ok"):
            log("⚠️ رد غير صالح من تيليجرام.")
            return []
        return body.get("result", [])

    def send_message(self, chat_id: int, text: str) -> int | None:
        """Send (splitting long texts). Returns first message_id."""
        first_id: int | None = None
        for chunk in _split(text):
            try:
                result = self._post(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                )
                if first_id is None:
                    first_id = (
                        result.get("result", {}).get("message_id")
                    )
            except Exception as exc:  # noqa: BLE001
                log("⚠️ فشل إرسال رسالة:", exc)
                return first_id
        return first_id

    def delete_message(
        self, chat_id: int, message_id: int
    ) -> None:
        try:
            self._post(
                "deleteMessage",
                {"chat_id": chat_id, "message_id": message_id},
            )
        except Exception:  # noqa: BLE001
            pass


def _split(text: str) -> list[str]:
    if not text:
        return ["…"]
    chunks: list[str] = []
    rest = text
    while len(rest) > MAX_TG_CHARS:
        cut = rest.rfind("\n", 0, MAX_TG_CHARS)
        if cut <= 0:
            cut = MAX_TG_CHARS
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    chunks.append(rest)
    return chunks


# ============================================================
# Remote confirmation (human-in-the-loop)
# ============================================================

class Confirmer:
    """Bridges ALIXAgent.confirm_fn with Telegram replies.

    ask() runs in the dispatcher thread; resolve() is called by the
    poll loop when the admin's next text arrives.
    """

    def __init__(self, api: BotAPI, admin_id: int):
        self._api = api
        self._admin_id = admin_id
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._answer: str | None = None
        self._pending = False

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._pending

    def ask(
        self, tool: str, arguments: dict, level: str | None
    ) -> bool:
        args_text = json.dumps(
            arguments, ensure_ascii=False
        )[:500]
        warn = "\n🚨 تحذير: هذه عملية تدميرية." if (
            level == "destructive"
        ) else ""
        prompt = (
            "⚠️ ALIX يطلب موافقة للتنفيذ\n"
            f"الأداة: {tool}\n"
            f"المستوى: {level}{warn}\n"
            f"المعاملات: {args_text}\n\n"
            "رد بـ «نعم» للسماح أو «لا» للرفض "
            f"(مهلة {CONFIRM_TIMEOUT}s)."
        )
        with self._lock:
            self._pending = True
            self._answer = None
            self._event.clear()

        self._api.send_message(self._admin_id, prompt)
        log(f"confirmation requested: {tool} ({level})")

        granted = self._event.wait(CONFIRM_TIMEOUT)

        with self._lock:
            self._pending = False
            answer = (self._answer or "").strip().lower()

        if not granted:
            self._api.send_message(
                self._admin_id,
                "⏱️ انتهت مهلة الموافقة — المهمة أُلغيت.",
            )
            log(f"confirmation timeout: {tool} -> deny")
            return False

        approved = answer in APPROVE_WORDS
        log(
            f"confirmation answer: {answer!r} -> "
            f"{'approve' if approved else 'deny'}"
        )
        return approved

    def resolve(self, text: str) -> bool:
        """Feed the admin's reply to a pending ask()."""
        with self._lock:
            if not self._pending:
                return False
            self._answer = text
            self._event.set()
            return True

    def cancel(self) -> bool:
        with self._lock:
            if not self._pending:
                return False
            self._answer = "لا"
            self._event.set()
            return True


# ============================================================
# Scheduled-approval poller (escalation path ب)
# === SCHEDULED-APPROVAL-POLLER v1 ===
# ============================================================
# The scheduler daemon writes destructive-tool approval requests to
# ~/ALIX-Agent/pending_approvals/requests/ and blocks up to 180s for a
# verdict. This poller (bot process) delivers the approval card and
# routes the admin's explicit نعم/لا to the queue. Card format mirrors
# Confirmer.ask() so the UX is identical. Anything that is not an
# explicit نعم/لا flows through to normal handling; the daemon's 180s
# timeout then cancels the request.

try:
    from core.scheduled_approval import (
        list_pending as _sa_list_pending,
        write_verdict as _sa_write_verdict,
        take_notifications as _sa_take_notifications,
    )

    _SA_AVAILABLE = True
except Exception as _sa_import_exc:  # noqa: BLE001
    _SA_AVAILABLE = False
    log(f"scheduled_approval unavailable: {_sa_import_exc}")

_scheduled_cards: dict = {}
_scheduled_lock = threading.Lock()
_DENY_WORDS = {"لا", "no", "n"}


def _send_scheduled_card(api: BotAPI, admin_id: int, req: dict) -> None:
    args_text = json.dumps(
        req.get("arguments") or {}, ensure_ascii=False
    )[:500]
    task = req.get("task_name") or req.get("task_id") or "مهمة مجدولة"
    prompt = (
        "⏳ مهمة مجدولة تطلب موافقة\n"
        f"المهمة: {task}\n"
        f"الأداة: {req.get('tool_name')}\n"
        f"المستوى: {req.get('level')}\n"
        f"المعاملات: {args_text}\n\n"
        "رد بـ «نعم» للسماح أو «لا» للرفض "
        f"(مهلة {CONFIRM_TIMEOUT}s)."
    )
    api.send_message(admin_id, prompt)
    log(
        "scheduled approval card sent: "
        f"{req.get('tool_name')} ({req.get('id')})"
    )


def poll_scheduled_approvals(api: BotAPI, admin_id: int) -> None:
    """Send cards for new requests; deliver outbox notifications."""
    if not _SA_AVAILABLE:
        return
    try:
        pending = _sa_list_pending()
    except Exception as exc:  # noqa: BLE001
        log(f"scheduled poll error: {exc}")
        return
    with _scheduled_lock:
        live_ids = set()
        for req in pending:
            rid = req["id"]
            live_ids.add(rid)
            if rid in _scheduled_cards:
                continue
            _scheduled_cards[rid] = req
            try:
                _send_scheduled_card(api, admin_id, req)
            except Exception as exc:  # noqa: BLE001
                log(f"scheduled card error: {exc}")
                del _scheduled_cards[rid]
        # Drop carded entries whose request vanished (expired daemon-side).
        for rid in list(_scheduled_cards):
            if rid not in live_ids:
                del _scheduled_cards[rid]
    try:
        for msg in _sa_take_notifications():
            api.send_message(admin_id, msg["text"])
    except Exception as exc:  # noqa: BLE001
        log(f"scheduled outbox error: {exc}")


def resolve_scheduled_approval(text: str) -> bool:
    """Route an explicit نعم/لا to the oldest carded scheduled request.

    Returns True if the text was consumed as a verdict.
    """
    if not _SA_AVAILABLE:
        return False
    t = (text or "").strip().lower()
    approved = t in APPROVE_WORDS
    if not approved and t not in _DENY_WORDS:
        return False
    with _scheduled_lock:
        if not _scheduled_cards:
            return False
        rid = next(iter(_scheduled_cards))
        req = _scheduled_cards.pop(rid)
    try:
        _sa_write_verdict(rid, approved, detail=(text or "").strip()[:100])
    except Exception as exc:  # noqa: BLE001
        log(f"scheduled verdict error: {exc}")
        return False
    log(
        "scheduled approval "
        f"{'granted' if approved else 'denied'}: "
        f"{req.get('tool_name')} ({rid})"
    )
    return True


def cancel_scheduled_approval() -> bool:
    """Deny the oldest carded scheduled approval (for /cancel)."""
    if not _SA_AVAILABLE:
        return False
    with _scheduled_lock:
        if not _scheduled_cards:
            return False
        rid = next(iter(_scheduled_cards))
        req = _scheduled_cards.pop(rid)
    try:
        _sa_write_verdict(rid, False, detail="/cancel")
    except Exception:  # noqa: BLE001
        return False
    log(
        "scheduled approval cancelled by /cancel: "
        f"{req.get('tool_name')} ({rid})"
    )
    return True


def _scheduled_poller_loop(api: BotAPI, admin_id: int) -> None:
    while True:
        try:
            poll_scheduled_approvals(api, admin_id)
        except Exception as exc:  # noqa: BLE001
            log(f"scheduled poller error: {exc}")
        time.sleep(5)


# ============================================================
# Dispatcher (sequential agent runs)
# ============================================================

HELP = (
    "🤖 ALIX عن بُعد\n\n"
    "أرسل أي أمر أو سؤال وسأنفذه عبر ALIX بنفس سياسة الأمان.\n"
    "الأدوات الحساسة تطلب موافقتك هنا قبل التنفيذ.\n\n"
    "/start — هذه الرسالة\n"
    "/cancel — إلغاء طلب موافقة معلّق"
)


class Dispatcher(threading.Thread):
    def __init__(
        self,
        api: BotAPI,
        admin_id: int,
        confirmer: Confirmer,
    ):
        super().__init__(daemon=True)
        self._api = api
        self._admin_id = admin_id
        self._confirmer = confirmer
        self._inbox: queue.Queue[str] = queue.Queue()
        self._agent = ALIXAgent()
        self._agent.confirm_fn = confirmer.ask
        log("ALIXAgent ready (confirm_fn hooked).")

    def submit(self, text: str) -> None:
        self._inbox.put(text)

    def run(self) -> None:  # noqa: D102
        while True:
            text = self._inbox.get()
            try:
                self._handle(text)
            except GroqFailover as exc:
                log("⚠️ فشل التحويل (المحلي متوقف):", exc)
                traceback.print_exc()
                self._api.send_message(
                    self._admin_id,
                    "⚠️ تعذّر إكمال الطلب: وصلنا لحدّ خدمة النماذج الآن "
                    "والمحرك المحلي متوقف. أعد المحاولة بعد دقيقة.",
                )
            except Exception as exc:  # noqa: BLE001
                log("❌ خطأ في المعالجة:", exc)
                traceback.print_exc()
                self._api.send_message(
                    self._admin_id,
                    "❌ خطأ داخلي أثناء التنفيذ.",
                )

    def _handle(self, text: str) -> None:
        wait_id = self._api.send_message(
            self._admin_id, "⏳ جارٍ التنفيذ..."
        )
        try:
            reply = self._agent.run(text)
        finally:
            if wait_id is not None:
                self._api.delete_message(
                    self._admin_id, wait_id
                )
        self._api.send_message(
            self._admin_id, reply or "تم."
        )


# ============================================================
# Single-instance guard
# ============================================================

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def claim_single_instance() -> None:
    TG_DIR.mkdir(parents=True, exist_ok=True)
    if PID_FILE.is_file():
        try:
            old = int(PID_FILE.read_text().strip())
        except ValueError:
            old = 0
        if old and _pid_alive(old):
            log(f"❌ البوت يعمل أصلًا (pid {old}).")
            sys.exit(1)
    PID_FILE.write_text(str(os.getpid()))
    atexit.register(
        lambda: PID_FILE.unlink(missing_ok=True)
    )


# ============================================================
# Update routing (one update -> next offset)
# ============================================================

def route_update(
    update: dict,
    api: "BotAPI",
    admin_id: int,
    confirmer: Confirmer,
    dispatcher: Dispatcher,
) -> int:
    """Route a single Telegram update. Returns the next offset."""
    offset = update["update_id"] + 1
    message = update.get("message") or {}
    sender = (message.get("from") or {}).get("id")

    # Admin-only: silently ignore everyone else.
    if sender != admin_id:
        return offset

    text = extract_text(message)
    if text is None:
        api.send_message(admin_id, "أرسل نصًا فقط حاليًا.")
        return offset

    chat_id = message["chat"]["id"]

    if text == "/cancel":
        if confirmer.cancel():
            api.send_message(chat_id, "🚫 أُلغي طلب الموافقة.")
        elif cancel_scheduled_approval():
            api.send_message(chat_id, "🚫 أُلغي طلب الموافقة المجدولة.")
        else:
            api.send_message(chat_id, "لا يوجد طلب معلّق.")
        return offset

    if confirmer.pending:
        # The next admin text answers the pending
        # confirmation (نعم / لا).
        confirmer.resolve(text)
        return offset

    # Scheduled approvals (escalation path ب): an explicit نعم/لا
    # answers the oldest carded scheduled request; anything else
    # flows through to normal handling.
    if resolve_scheduled_approval(text):
        return offset

    if text == "/start":
        api.send_message(chat_id, HELP)
        return offset

    # /notify <message> — send a proactive Telegram message to self
    if text.lower().startswith("/notify "):
        try:
            import subprocess
            msg = text[8:].strip()
            if not msg:
                api.send_message(chat_id, "❌ الاستخدام: /notify <نص الرسالة>")
            else:
                r = subprocess.run(
                    ["python3", "send_telegram.py", msg],
                    capture_output=True, text=True, timeout=20, cwd="/home/ubuntu/ALIX-Agent",
                )
                if r.returncode == 0:
                    api.send_message(chat_id, "✅ تم إرسال الإشعار.")
                else:
                    api.send_message(chat_id, "❌ فشل الإرسال: " + (r.stderr or "?")[:150])
        except Exception as e:
            api.send_message(chat_id, "❌ خطأ: " + str(e)[:150])
        return offset

    # /call and /sms — direct commands (policy-compliant: explicit confirmation required)
    # These enqueue to phone_queue; the phone_poller asks for final confirmation on-device.
    _is_call_cmd = text.lower().startswith("/call ")
    _is_sms_cmd = text.lower().startswith("/sms ")
    if _is_call_cmd or _is_sms_cmd:
        try:
            import json as _json
            import re as _re
            import time as _time
            from pathlib import Path as _Path

            _queue_dir = _Path("/home/ubuntu/ALIX-Agent/phone_queue/requests")
            _queue_dir.mkdir(parents=True, exist_ok=True)

            if _is_call_cmd:
                _number = _re.sub(r"[\s-]", "", text[6:].strip())
                if not _re.fullmatch(r"\+?\d{8,15}", _number):
                    api.send_message(chat_id, "❌ رقم غير صالح. الاستخدام: /call <رقم>")
                    return offset
                _req = {
                    "type": "call",
                    "number": _number,
                    "requested_by": "telegram",
                    "timestamp": _time.time(),
                    "status": "pending_confirmation",
                }
                _req_file = _queue_dir / f"call_{int(_time.time())}.json"
                _req_file.write_text(_json.dumps(_req, ensure_ascii=False), encoding="utf-8")
                api.send_message(
                    chat_id,
                    f"📞 طلب مكالمة إلى {_number} تم إدراجه.\n"
                    f"شغّل ~/phone_poller.sh على الهاتف للتأكيد والتنفيذ.",
                )
            else:  # /sms
                _parts = text[5:].strip().split(" ", 1)
                if len(_parts) < 2:
                    api.send_message(chat_id, "❌ الاستخدام: /sms <رقم> <نص الرسالة>")
                    return offset
                _number = _re.sub(r"[\s-]", "", _parts[0])
                _msg = _parts[1].strip()
                if not _re.fullmatch(r"\+?\d{8,15}", _number):
                    api.send_message(chat_id, "❌ رقم غير صالح.")
                    return offset
                if len(_msg) > 500:
                    api.send_message(chat_id, "❌ الرسالة طويلة (الحد 500 حرف).")
                    return offset
                _req = {
                    "type": "sms",
                    "number": _number,
                    "message": _msg,
                    "requested_by": "telegram",
                    "timestamp": _time.time(),
                    "status": "pending_confirmation",
                }
                _req_file = _queue_dir / f"sms_{int(_time.time())}.json"
                _req_file.write_text(_json.dumps(_req, ensure_ascii=False), encoding="utf-8")
                api.send_message(
                    chat_id,
                    f"💬 طلب رسالة إلى {_number} تم إدراجه.\n"
                    f"شغّل ~/phone_poller.sh على الهاتف للتأكيد والتنفيذ.",
                )
        except Exception as e:
            api.send_message(chat_id, "❌ خطأ: " + str(e)[:150])
        return offset

    # /contacts <name> — search synced phone contacts
    if text.lower().startswith("/contacts "):
        try:
            import json as _json
            from pathlib import Path as _Path

            _query = text[10:].strip().lower()
            _contacts_file = _Path("/home/ubuntu/ALIX-Agent/phone_queue/contacts.json")
            if not _contacts_file.is_file():
                api.send_message(chat_id, "❌ ملف جهات الاتصال غير موجود. شغّل ~/contacts_sync.sh على الهاتف.")
                return offset

            _contacts = _json.loads(_contacts_file.read_text(encoding="utf-8"))
            _matches = []
            for _c in _contacts:
                _name = str(_c.get("name", "")).lower()
                if _query in _name:
                    _numbers = _c.get("numbers", _c.get("phone", _c.get("number", "?")))
                    if isinstance(_numbers, list):
                        _nums = ", ".join(str(n) for n in _numbers[:3])
                    else:
                        _nums = str(_numbers)
                    _matches.append(f"• {_c.get('name', '?')}: {_nums}")
                    if len(_matches) >= 10:
                        break

            if _matches:
                api.send_message(chat_id, "📇 نتائج البحث:\n" + "\n".join(_matches))
            else:
                api.send_message(chat_id, f"❌ لم أجد '{_query}' في جهات الاتصال.")
        except Exception as e:
            api.send_message(chat_id, "❌ خطأ: " + str(e)[:150])
        return offset

    # /gmail — explicit command forms ONLY. Root cause #3 of
    # the 2026-10-27 E2E failures: this shortcut used to fire
    # on a bare substring match, so ANY sentence merely
    # mentioning mail (e.g. the ordered 4-step task ending in
    # «ابحث في Gmail…») was swallowed here with a canned
    # latest-5 dump — the message never reached the
    # Dispatcher, leaving no audit trail and no plan. The
    # router transports; the agent decides. A shortcut may
    # only claim a message that IS the command: "/gmail",
    # "/gmail <query>", or a bare keyword alone.
    _gmail_keywords = (
        "بريد", "جميل", "gmail", "email",
        "ايميل", "رسائل", "inbox", "صندوق الوارد",
    )
    _gmail_query: str | None = None
    _text_norm = text.strip().lower()
    if _text_norm == "/gmail" or _text_norm in _gmail_keywords:
        _gmail_query = ""
    elif _text_norm.startswith("/gmail "):
        _gmail_query = text.strip()[len("/gmail "):].strip()
    if _gmail_query is not None:
        # Direct Gmail fetch — bypasses LLM entirely.
        try:
            from dotenv import load_dotenv
            from pathlib import Path
            load_dotenv(Path(__file__).parent / ".env")
            from core.feature_bridge import build_gmail_search_controller
            ctrl = build_gmail_search_controller()
            result = ctrl.handle(
                {"query": _gmail_query, "max_results": 5}
            )
            if not result.get("ok"):
                api.send_message(
                    chat_id,
                    "❌ خطأ في جلب البريد: "
                    + str(result.get("error", "?"))[:200]
                )
            else:
                msgs = result.get("messages", [])
                if not msgs:
                    api.send_message(chat_id, "📭 لا توجد رسائل.")
                else:
                    lines = ["📧 أحدث الرسائل:\n"]
                    for m in msgs[:5]:
                        subj = str(m.get("subject", "(بدون موضوع)"))[:60]
                        frm = str(m.get("from", "?"))[:40]
                        dt = str(m.get("date", ""))[:20]
                        acct = str(m.get("account", "")).split("@")[0]
                        acct_line = f"\n  📬 {acct}" if acct else ""
                        lines.append(f"• {subj}\n  من: {frm}\n  {dt}{acct_line}\n")
                    api.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            api.send_message(chat_id, "❌ خطأ: " + str(e)[:200])
        return offset

    # --- Voice note handling (ALIX الصوتي Phase 1) ---
    # If the incoming message has a voice note, transcribe it via
    # Groq Whisper and use the transcript as the user text.
    # Transcripts are UNTRUSTED input: routed as text through Policy.
    voice = message.get("voice") if isinstance(message, dict) else None
    if voice and isinstance(voice, dict) and voice.get("file_id"):
        try:
            from core.feature_bridge import (# noqa
                build_voice_transcribe_controller)
            import os
            _vc = build_voice_transcribe_controller()
            _vr = _vc.handle({
                "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                "file_id": voice["file_id"],
                "language": "ar",
            })
            if _vr.get("ok") and _vr.get("transcript", "").strip():
                text = "🎙️ " + _vr["transcript"].strip()
            else:
                api.send_message(chat_id,
                    "❌ تعذر تفريغ الرسالة الصوتية: "
                    + str(_vr.get("error", "?"))[:150])
                return offset
        except Exception as _ve:
            api.send_message(chat_id,
                "❌ خطأ في معالجة الصوت: " + str(_ve)[:150])
            return offset
    dispatcher.submit(text)
    return offset


# ============================================================
# Poll loop
# ============================================================

def extract_text(message: dict) -> str | None:
    text = message.get("text")
    return text.strip() if isinstance(text, str) else None


def main() -> None:
    token, admin_id = load_config()
    claim_single_instance()

    api = BotAPI(token)
    confirmer = Confirmer(api, admin_id)
    dispatcher = Dispatcher(api, admin_id, confirmer)
    dispatcher.start()

    # Scheduled-approval poller (escalation path ب): delivers cards
    # for daemon-side destructive requests + outbox notifications.
    _sched_thread = threading.Thread(
        target=_scheduled_poller_loop,
        args=(api, admin_id),
        daemon=True,
        name="scheduled-approvals",
    )
    _sched_thread.start()

    # Flush stale updates so we don't replay history on restart.
    try:
        stale = api.get_updates(None, 0)
        offset = (
            max(u["update_id"] for u in stale) + 1
            if stale
            else None
        )
    except Exception as exc:  # noqa: BLE001
        log("❌ فشل الاتصال الأول بتيليجرام:", exc)
        sys.exit(1)

    me = api._post("getMe", {})
    log(
        "متصل كبوت:",
        me.get("result", {}).get("username"),
        "| admin:",
        admin_id,
    )
    api.send_message(
        admin_id, "🤖 ALIX متصل عبر تيليجرام. /start للمساعدة."
    )

    while True:
        try:
            updates = api.get_updates(offset, POLL_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            log("⚠️ خطأ في الاستطلاع:", exc)
            time.sleep(5)
            continue

        for update in updates:
            offset = route_update(
                update, api, admin_id, confirmer, dispatcher
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("توقف البوت.")
