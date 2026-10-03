"""Gmail IMAP/SMTP gateway for ALIX-Agent.

Stdlib only (imaplib, smtplib, email). Credentials come from the
environment (GMAIL_ADDRESS, GMAIL_APP_PASSWORD) and are never logged.

Fail-closed: every method returns {"ok": False, "error": ...} when the
gateway is not configured or the network operation fails.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import os
import re
import smtplib
import socket

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
NET_TIMEOUT = 30

_MAX_RESULTS = 25
_MAX_BODY_CHARS = 20000
_MAX_SUBJECT_CHARS = 300

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _decode_header(value) -> str:
    if not value:
        return ""
    parts = []
    for text, charset in email.header.decode_header(value):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(charset or "utf-8", errors="replace"))
            except Exception:
                parts.append(text.decode("utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def _body_text(msg) -> str:
    """Extract readable plain-text from a message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except Exception:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        text = msg.get_payload()
        return text if isinstance(text, str) else ""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


class GmailGateway:
    """Thin IMAP/SMTP wrapper. One instance per operation; no state kept."""

    def __init__(self, address: str | None = None, app_password: str | None = None):
        self.address = (address or os.environ.get("GMAIL_ADDRESS", "")).strip()
        # App passwords may contain spaces; strip them (Gmail ignores spaces).
        raw = app_password or os.environ.get("GMAIL_APP_PASSWORD", "")
        self.app_password = re.sub(r"\s+", "", raw or "")

    def _configured(self) -> dict | None:
        if not self.address or not _EMAIL_RE.match(self.address):
            return {"ok": False, "error": "GMAIL_ADDRESS غير مضبوط أو غير صالح."}
        if not self.app_password:
            return {"ok": False, "error": "GMAIL_APP_PASSWORD غير مضبوط."}
        return None

    def _imap(self) -> imaplib.IMAP4_SSL:
        return imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=NET_TIMEOUT)

    # ---------------------------------------------------------- search
    def search(self, query: str = "", limit: int = 10) -> dict:
        bad = self._configured()
        if bad:
            return bad
        try:
            limit = max(1, min(int(limit), _MAX_RESULTS))
        except (TypeError, ValueError):
            limit = 10
        query = (query or "").strip()[:200]
        try:
            imap = self._imap()
            try:
                imap.login(self.address, self.app_password)
                imap.select("INBOX", readonly=True)
                if query:
                    # IMAP TEXT search; fall back to ALL on parse failure.
                    typ, data = imap.uid("search", None, "TEXT", f'"{query}"')
                    if typ != "OK":
                        typ, data = imap.uid("search", None, "ALL")
                else:
                    typ, data = imap.uid("search", None, "ALL")
                if typ != "OK":
                    return {"ok": False, "error": "فشل البحث في Gmail."}
                uids = (data[0] or b"").split()
                uids = uids[-limit:]
                results = []
                for uid in reversed(uids):
                    typ, msg_data = imap.uid(
                        "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
                    )
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    results.append(
                        {
                            "uid": uid.decode("utf-8", errors="replace"),
                            "from": _decode_header(msg.get("From")),
                            "subject": _decode_header(msg.get("Subject")),
                            "date": msg.get("Date", ""),
                        }
                    )
                return {"ok": True, "messages": results, "count": len(results)}
            finally:
                try:
                    imap.logout()
                except Exception:
                    pass
        except (imaplib.IMAP4.error, socket.error, OSError) as exc:
            return {"ok": False, "error": f"تعذر الاتصال بـ Gmail: {exc}"}

    # ------------------------------------------------------------ read
    def read(self, uid: str) -> dict:
        bad = self._configured()
        if bad:
            return bad
        uid = (uid or "").strip()
        if not re.fullmatch(r"[0-9]+", uid):
            return {"ok": False, "error": "معرف الرسالة غير صالح."}
        try:
            imap = self._imap()
            try:
                imap.login(self.address, self.app_password)
                imap.select("INBOX", readonly=True)
                typ, msg_data = imap.uid("fetch", uid.encode(), "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    return {"ok": False, "error": "الرسالة غير موجودة."}
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                body = _body_text(msg)[:_MAX_BODY_CHARS]
                return {
                    "ok": True,
                    "uid": uid,
                    "from": _decode_header(msg.get("From")),
                    "to": _decode_header(msg.get("To")),
                    "subject": _decode_header(msg.get("Subject")),
                    "date": msg.get("Date", ""),
                    "body": body,
                }
            finally:
                try:
                    imap.logout()
                except Exception:
                    pass
        except (imaplib.IMAP4.error, socket.error, OSError) as exc:
            return {"ok": False, "error": f"تعذر قراءة الرسالة: {exc}"}

    # ------------------------------------------------------------ send
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
    ) -> dict:
        bad = self._configured()
        if bad:
            return bad
        to = (to or "").strip()
        if not _EMAIL_RE.match(to):
            return {"ok": False, "error": "البريد المستلم غير صالح."}
        subject = (subject or "").strip()[:_MAX_SUBJECT_CHARS]
        body = (body or "").strip()
        if not body:
            return {"ok": False, "error": "نص الرسالة فارغ."}
        if len(body) > _MAX_BODY_CHARS:
            return {"ok": False, "error": "نص الرسالة طويل جدًا."}

        msg = email.message.EmailMessage()
        msg["From"] = self.address
        msg["To"] = to
        msg["Subject"] = subject or "(بلا موضوع)"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to.strip()[:500]
        msg.set_content(body)

        try:
            with smtplib.SMTP_SSL(
                SMTP_HOST, SMTP_PORT, timeout=NET_TIMEOUT
            ) as smtp:
                smtp.login(self.address, self.app_password)
                smtp.send_message(msg)
            return {"ok": True, "to": to, "subject": msg["Subject"]}
        except (smtplib.SMTPException, socket.error, OSError) as exc:
            return {"ok": False, "error": f"تعذر إرسال البريد: {exc}"}
