"""Termux:API gateway for phone actions.

Security properties:
- NEVER uses a shell: every command is an argv list with shell=False.
- Phone numbers are strictly validated (digits and phone punctuation
  only); anything else is rejected before any subprocess starts.
- Message/title/content have hard length caps.
- Every call has a timeout; missing Termux:API fails closed.
"""
from __future__ import annotations

import re
import shutil
import subprocess

# Optional leading +, then 5..20 chars of digits and phone punctuation,
# must end with a digit. Examples: +212612345678, 0612345678,
# +1 (555) 123-4567
_NUMBER_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{4,18}[0-9]$")

MAX_SMS_CHARS = 500  # aligned with Policy.max_argument_length
MAX_TITLE_CHARS = 100
MAX_CONTENT_CHARS = 500


class TermuxApiGateway:
    """Executes termux-*-api commands without a shell."""

    @staticmethod
    def valid_number(number: str) -> bool:
        return (
            isinstance(number, str)
            and bool(_NUMBER_RE.match(number.strip()))
        )

    def _run(self, argv: list, timeout: int) -> dict:
        if shutil.which(argv[0]) is None:
            return {
                "ok": False,
                "error": "Termux:API غير مثبت: %s" % argv[0],
            }
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "انتهت المهلة."}
        except OSError as e:
            return {"ok": False, "error": str(e)[:200]}
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-300:],
        }

    def place_call(self, number: str) -> dict:
        number = (number or "").strip()
        if not self.valid_number(number):
            return {
                "ok": False,
                "action": "phone_call",
                "message": "رقم هاتف غير صالح.",
                "evidence": {},
            }
        r = self._run(["termux-telephony-call", number], timeout=30)
        if not r["ok"]:
            return {
                "ok": False,
                "action": "phone_call",
                "message": "تعذر إجراء المكالمة: %s"
                % r.get("error", "رمز %s" % r.get("returncode")),
                "evidence": {"number": number},
            }
        return {
            "ok": True,
            "action": "phone_call",
            "message": "بدأ الاتصال.",
            "evidence": {"number": number},
        }

    def send_sms(self, number: str, message: str) -> dict:
        number = (number or "").strip()
        message = (message or "")[:MAX_SMS_CHARS]
        if not self.valid_number(number):
            return {
                "ok": False,
                "action": "send_sms",
                "message": "رقم هاتف غير صالح.",
                "evidence": {},
            }
        if not message.strip():
            return {
                "ok": False,
                "action": "send_sms",
                "message": "نص الرسالة فارغ.",
                "evidence": {},
            }
        r = self._run(
            ["termux-sms-send", "-n", number, message], timeout=30
        )
        if not r["ok"]:
            return {
                "ok": False,
                "action": "send_sms",
                "message": "تعذر إرسال الرسالة: %s"
                % r.get("error", "رمز %s" % r.get("returncode")),
                "evidence": {"number": number},
            }
        return {
            "ok": True,
            "action": "send_sms",
            "message": "أُرسلت الرسالة.",
            "evidence": {"number": number, "chars": len(message)},
        }

    def notify(self, title: str, content: str) -> dict:
        title = (title or "ALIX")[:MAX_TITLE_CHARS]
        content = (content or "")[:MAX_CONTENT_CHARS]
        if not content.strip():
            return {
                "ok": False,
                "action": "notify",
                "message": "محتوى التنبيه فارغ.",
                "evidence": {},
            }
        r = self._run(
            ["termux-notification", "--title", title, "--content", content],
            timeout=10,
        )
        if not r["ok"]:
            return {
                "ok": False,
                "action": "notify",
                "message": "تعذر عرض التنبيه: %s"
                % r.get("error", "رمز %s" % r.get("returncode")),
                "evidence": {},
            }
        return {
            "ok": True,
            "action": "notify",
            "message": "عُرض التنبيه.",
            "evidence": {"title": title},
        }
