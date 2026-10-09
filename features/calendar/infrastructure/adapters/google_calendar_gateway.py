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
import time
import urllib.error
import urllib.parse
import urllib.request

_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_NET_TIMEOUT = 30


class GoogleCalendarGateway:
    """CalendarGateway backed by Google Calendar API v3."""

    def __init__(self) -> None:
        self._client_id = os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "")
        self._client_secret = os.environ.get(
            "GOOGLE_CALENDAR_CLIENT_SECRET", ""
        )
        self._refresh_token = os.environ.get(
            "GOOGLE_CALENDAR_REFRESH_TOKEN", ""
        )
        self._access_token = ""
        self._token_expiry = 0.0

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
            return {
                "ok": False,
                "error": f"HTTP {exc.code}",
            }
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}

    # ----------------------------------------------------------
    # CalendarGateway port
    # ----------------------------------------------------------

    def list_events(
        self, time_min: str, time_max: str, max_results: int
    ) -> dict:
        query = urllib.parse.urlencode(
            {
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
                "singleEvents": "true",
                "orderBy": "startTime",
            }
        )
        result = self._request("GET", f"/calendars/primary/events?{query}")
        if not result["ok"]:
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
            return result
        return {"ok": True}
