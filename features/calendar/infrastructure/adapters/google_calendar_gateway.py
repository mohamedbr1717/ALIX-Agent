"""Google Calendar gateway (stdlib only: urllib).

Credentials come from the environment and are never logged:
- GOOGLE_CALENDAR_CLIENT_ID
- GOOGLE_CALENDAR_CLIENT_SECRET
- GOOGLE_CALENDAR_REFRESH_TOKEN

Fail-closed: every method returns {"ok": False, "error": ...} when the
gateway is not configured or the network operation fails.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_NET_TIMEOUT = 30

try:
    from zoneinfo import ZoneInfo

    _LOCAL_TZ = ZoneInfo("Africa/Casablanca")
except Exception:  # tzdata unavailable (rare) — Morocco is UTC+1
    _LOCAL_TZ = timezone(timedelta(hours=1))

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _qualify_bound(value: str, *, end_of_day: bool) -> str | None:
    """Normalize one list-range bound to RFC 3339 with an offset.

    Google Calendar rejects naive timeMin/timeMax with HTTP 400.
    Naive values are read as Africa/Casablanca local time (the same
    convention add_event uses); a date-only bound expands to the
    start/end of that local day; already-qualified values keep their
    offset. Unparseable input returns None so the caller fails closed
    without calling Google.
    """
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if _DATE_ONLY_RE.match(text) and end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_LOCAL_TZ)
    return parsed.isoformat()


class GoogleCalendarGateway:
    """CalendarGateway backed by Google Calendar API v3."""

    def __init__(self) -> None:
        self._ensure_env()
        self._access_token = ""
        self._token_expiry = 0.0

    def _ensure_env(self) -> None:
        """Load credentials from os.environ, falling back to .env file."""
        self._client_id = os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "")
        self._client_secret = os.environ.get(
            "GOOGLE_CALENDAR_CLIENT_SECRET", ""
        )
        self._refresh_token = os.environ.get(
            "GOOGLE_CALENDAR_REFRESH_TOKEN", ""
        )
        if not (self._client_id and self._client_secret and self._refresh_token):
            # telegram_bot.py loads .env lazily; try it here too.
            try:
                from dotenv import load_dotenv
                from pathlib import Path

                load_dotenv(Path.home() / "ALIX-Agent" / ".env")
                self._client_id = os.environ.get(
                    "GOOGLE_CALENDAR_CLIENT_ID", ""
                )
                self._client_secret = os.environ.get(
                    "GOOGLE_CALENDAR_CLIENT_SECRET", ""
                )
                self._refresh_token = os.environ.get(
                    "GOOGLE_CALENDAR_REFRESH_TOKEN", ""
                )
            except Exception:
                pass

    # ----------------------------------------------------------
    # Configuration
    # ----------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(
            self._client_id and self._client_secret and self._refresh_token
        )

    # ----------------------------------------------------------
    # OAuth2 token handling
    # ----------------------------------------------------------

    def _refresh_access_token(self) -> bool:
        """Exchange refresh token for a fresh access token."""
        if not self.is_configured():
            return False
        # Reuse a still-valid token.
        if self._access_token and time.time() < self._token_expiry - 60:
            return True
        try:
            payload = urllib.parse.urlencode(
                {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                _TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(
                request, timeout=_NET_TIMEOUT
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
            token = data.get("access_token", "")
            if not token:
                return False
            self._access_token = token
            expires_in = int(data.get("expires_in", 3600))
            self._token_expiry = time.time() + expires_in
            return True
        except Exception:
            self._access_token = ""
            return False

    # ----------------------------------------------------------
    # HTTP helpers
    # ----------------------------------------------------------

    def _request(
        self, method: str, path: str, body: dict | None = None
    ) -> dict:
        if not self._refresh_access_token():
            return {
                "ok": False,
                "error": "التقويم غير مُهيأ أو فشل تجديد التفويض.",
            }
        try:
            data = None
            headers = {
                "Authorization": f"Bearer {self._access_token}",
            }
            if body is not None:
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(
                _CALENDAR_API + path,
                data=data,
                headers=headers,
                method=method,
            )
            with urllib.request.urlopen(
                request, timeout=_NET_TIMEOUT
            ) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return {"ok": True, "data": {}}
                return {"ok": True, "data": json.loads(raw)}
        except urllib.error.HTTPError as exc:
            result = {"ok": False, "error": f"HTTP {exc.code}"}
            # Surface Google's own diagnostic message when present —
            # a bare "HTTP 400" hides the cause. The "error" string
            # itself is unchanged: delete_event matches it exactly.
            try:
                payload = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = str(payload.get("error", {}).get("message", "")).strip()
                if detail:
                    result["detail"] = detail[:200]
            except Exception:
                pass
            return result
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}

    # ----------------------------------------------------------
    # CalendarGateway port
    # ----------------------------------------------------------

    def list_events(
        self, time_min: str, time_max: str, max_results: int
    ) -> dict:
        qualified_min = _qualify_bound(time_min, end_of_day=False)
        qualified_max = _qualify_bound(time_max, end_of_day=True)
        if qualified_min is None or qualified_max is None:
            return {"ok": False, "error": "نطاق زمني غير صالح للإدراج."}
        if datetime.fromisoformat(qualified_min) > datetime.fromisoformat(
            qualified_max
        ):
            return {
                "ok": False,
                "error": "النطاق الزمني معكوس: البداية بعد النهاية.",
            }
        query = urllib.parse.urlencode(
            {
                "timeMin": qualified_min,
                "timeMax": qualified_max,
                "maxResults": max_results,
                "singleEvents": "true",
                "orderBy": "startTime",
            }
        )
        result = self._request("GET", f"/calendars/primary/events?{query}")
        if not result["ok"]:
            detail = result.get("detail")
            if detail:
                return {"ok": False, "error": f"{result['error']}: {detail}"}
            return result
        items = result["data"].get("items", [])
        events = []
        for item in items:
            start = item.get("start", {})
            end = item.get("end", {})
            events.append(
                {
                    "event_id": item.get("id", ""),
                    "title": item.get("summary", ""),
                    "start": start.get("dateTime", start.get("date", "")),
                    "end": end.get("dateTime", end.get("date", "")),
                    "description": item.get("description", ""),
                }
            )
        return {"ok": True, "events": events}

    def add_event(self, event: dict) -> dict:
        timezone = event.get("timezone", "Africa/Casablanca")
        body = {
            "summary": event.get("title", ""),
            "description": event.get("description", ""),
            "start": {
                "dateTime": event.get("start", ""),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": event.get("end", ""),
                "timeZone": timezone,
            },
        }
        result = self._request(
            "POST", "/calendars/primary/events", body
        )
        if not result["ok"]:
            return result
        return {
            "ok": True,
            "event_id": result["data"].get("id", ""),
        }

    def delete_event(self, event_id: str) -> dict:
        encoded = urllib.parse.quote(event_id, safe="")
        result = self._request(
            "DELETE", f"/calendars/primary/events/{encoded}"
        )
        if not result["ok"]:
            # Idempotent delete: the desired end-state is "event absent".
            # 404/410 means it is already absent -> report success.
            if result.get("error") in ("HTTP 404", "HTTP 410"):
                return {"ok": True, "already_deleted": True}
            return result
        return {"ok": True}

    def get_event(self, event_id: str) -> dict:
        """Read one event back by id (Decision 2's verify channel).

        404/410 is a SUCCESSFUL read with found=False — the event
        is absent. Any other failure keeps ok=False so callers can
        tell "proven absent" from "could not read" (UNKNOWN).
        """
        encoded = urllib.parse.quote(event_id, safe="")
        result = self._request(
            "GET", f"/calendars/primary/events/{encoded}"
        )
        if not result["ok"]:
            if result.get("error") in ("HTTP 404", "HTTP 410"):
                return {"ok": True, "found": False}
            return result
        item = result["data"]
        start = item.get("start", {})
        end = item.get("end", {})
        return {
            "ok": True,
            "found": True,
            "event": {
                "event_id": item.get("id", ""),
                "title": item.get("summary", ""),
                "start": start.get(
                    "dateTime", start.get("date", "")
                ),
                "end": end.get("dateTime", end.get("date", "")),
                "description": item.get("description", ""),
            },
        }
