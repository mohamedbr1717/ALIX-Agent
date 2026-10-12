"""Meta WhatsApp Cloud API gateway (official API, stdlib only).

Security properties:
- Credentials come from the real environment, falling back to the
  repo-root .env file (same mechanism the live bot uses: telegram_bot.py
  reads .env via dotenv_values() into a dict and never injects it into
  os.environ, so os.environ alone is not sufficient there).
  Missing credentials fail closed.
- Recipient numbers are strictly validated and normalized to digits;
  anything else is rejected before any network call.
- Message text has a hard length cap (WhatsApp limit: 4096 chars).
- Every call has a timeout; network errors fail closed with a short
  Arabic message. Meta error codes are mapped to actionable text;
  the access token is never logged or echoed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - optional, stdlib-only fallback
    dotenv_values = None  # type: ignore[assignment]

GRAPH_HOST = "graph.facebook.com"
DEFAULT_API_VERSION = "v26.0"
TIMEOUT_S = 20
MAX_TEXT_CHARS = 4096

# Cloud API wants digits only (no '+', spaces or dashes), 7..15 digits.
_DIGITS_RE = re.compile(r"^[0-9]{7,15}$")

# Meta error codes worth translating (stable across versions).
_ERROR_HINTS = {
    190: "رمز الوصول منتهٍ أو غير صالح — جدّد الرمز من لوحة Meta.",
    131030: "الرقم المستلم غير مسجّل في قائمة أرقام الاختبار (حتى 5 أرقام).",
    131047: "خارج نافذة الـ24 ساعة — يلزم قالب (template) معتمد.",
    132000: "رقم الهاتف التجريبي غير مرتبط بحساب WhatsApp Business.",
}


def _resolve_env(name: str) -> str:
    """Config lookup: real environment first, repo-root .env second.

    The live bot (telegram_bot.py) loads .env with dotenv_values() into a
    plain dict and never puts those values into os.environ, so reading
    os.environ alone misses them. This mirrors the bot's own mechanism.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if dotenv_values is None:
        return ""
    try:
        # cloud_api_gateway.py is at
        #   <repo>/features/whatsapp/infrastructure/adapters/
        # -> five parents up is the repo root.
        repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        data = dotenv_values(repo_root / ".env") or {}
        return str(data.get(name) or "").strip()
    except Exception:
        return ""


class CloudApiGateway:
    """Sends WhatsApp messages via Meta's official Cloud API."""

    def __init__(self) -> None:
        self._phone_number_id = _resolve_env("WHATSAPP_PHONE_NUMBER_ID")
        self._token = _resolve_env("WHATSAPP_ACCESS_TOKEN")
        self._version = _resolve_env("WHATSAPP_API_VERSION") or DEFAULT_API_VERSION

    @staticmethod
    def normalize_number(to: str) -> str:
        """'+212 6-23-93-13-32' -> '212623931332'. Empty string if invalid."""
        if not isinstance(to, str):
            return ""
        digits = re.sub(r"[^0-9]", "", to)
        # Strip a single leading 0 trunk prefix only when it looks local
        # (e.g. '0612345678' without country code is ambiguous -> reject).
        if not _DIGITS_RE.match(digits):
            return ""
        return digits

    def _configured(self) -> str:
        if not self._phone_number_id:
            return "WHATSAPP_PHONE_NUMBER_ID غير مضبوط في البيئة."
        if not self._token:
            return "WHATSAPP_ACCESS_TOKEN غير مضبوط في البيئة."
        return ""

    def send_text(self, to: str, text: str) -> dict:
        missing = self._configured()
        if missing:
            return {"ok": False, "action": "whatsapp_send", "error": missing}
        recipient = self.normalize_number(to)
        if not recipient:
            return {
                "ok": False,
                "action": "whatsapp_send",
                "error": "رقم الهاتف غير صالح (يلزم 7..15 رقمًا).",
            }
        body = text if isinstance(text, str) else ""
        if not body.strip():
            return {
                "ok": False,
                "action": "whatsapp_send",
                "error": "نص الرسالة فارغ.",
            }
        if len(body) > MAX_TEXT_CHARS:
            return {
                "ok": False,
                "action": "whatsapp_send",
                "error": f"الرسالة أطول من الحد ({MAX_TEXT_CHARS} حرفًا).",
            }

        url = (
            f"https://{GRAPH_HOST}/{self._version}/"
            f"{self._phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": body, "preview_url": False},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            return {
                "ok": False,
                "action": "whatsapp_send",
                "error": self._meta_error(e),
            }
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {
                "ok": False,
                "action": "whatsapp_send",
                "error": "تعذر الوصول إلى Meta: %s" % str(e)[:120],
            }
        messages = data.get("messages") or []
        if messages and messages[0].get("id"):
            return {
                "ok": True,
                "action": "whatsapp_send",
                "message": "أُرسلت رسالة WhatsApp.",
                "message_id": messages[0]["id"],
                "to": recipient,
            }
        return {
            "ok": False,
            "action": "whatsapp_send",
            "error": "رد غير متوقع من Meta.",
        }

    def _meta_error(self, e: urllib.error.HTTPError) -> str:
        try:
            data = json.loads(e.read().decode("utf-8") or "{}")
            err = data.get("error", {})
            code = err.get("code")
            msg = str(err.get("message", ""))[:160]
        except Exception:
            code, msg = None, ""
        hint = _ERROR_HINTS.get(code, "")
        base = f"رفضت Meta الطلب (code {code}): {msg}" if code else (
            f"رفضت Meta الطلب (HTTP {e.code})."
        )
        return (base + " " + hint).strip()
