#!/usr/bin/env python3
"""Google Calendar OAuth2 authorization helper (run once on the VPS).

Reads the OAuth client JSON downloaded from Google Cloud Console,
prints an authorization URL, and exchanges the pasted code for a
refresh token. The refresh token is appended to .env — never printed
in full, never committed.

Usage:
    python3 calendar_auth.py /path/to/client_secret.json
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/calendar"
_REDIRECT = "urn:ietf:wg:oauth:2.0:oob"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/client_secret.json")
        return 2

    client_file = Path(sys.argv[1])
    if not client_file.is_file():
        print(f"❌ الملف غير موجود: {client_file}")
        return 1

    data = json.loads(client_file.read_text(encoding="utf-8"))
    # Support both "web"/"installed" formats.
    section = data.get("installed") or data.get("web") or {}
    client_id = section.get("client_id", "")
    client_secret = section.get("client_secret", "")
    if not client_id or not client_secret:
        print("❌ ملف JSON لا يحتوي client_id/client_secret.")
        return 1

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": _REDIRECT,
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    print("\n1) افتح هذا الرابط في المتصفح وسجّل الدخول واسمح بالوصول:\n")
    print(f"{_AUTH_URL}?{params}\n")
    print("2) انسخ رمز التفويض والصقه هنا:\n")
    try:
        code = input("الكود: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n❌ أُلغي.")
        return 1
    if not code:
        print("❌ كود فارغ.")
        return 1

    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _REDIRECT,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            tokens = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"❌ فشل تبادل الكود: {type(exc).__name__}")
        return 1

    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        print("❌ لم يُرجع Google refresh_token. أعد التفويض مع prompt=consent.")
        return 1

    # Append to .env (outside git).
    env_path = Path.home() / "ALIX-Agent" / ".env"
    lines = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    # Remove any previous calendar entries to keep .env idempotent.
    lines = [
        line
        for line in lines
        if not line.startswith("GOOGLE_CALENDAR_")
    ]
    lines += [
        f"GOOGLE_CALENDAR_CLIENT_ID={client_id}",
        f"GOOGLE_CALENDAR_CLIENT_SECRET={client_secret}",
        f"GOOGLE_CALENDAR_REFRESH_TOKEN={refresh_token}",
    ]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Remove the downloaded client JSON — secrets live in .env only.
    try:
        client_file.unlink()
        print(f"🗑️ حُذف ملف العميل: {client_file}")
    except OSError:
        pass

    print("✅ تم حفظ التفويض في .env. أعد تشغيل alix-bot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
