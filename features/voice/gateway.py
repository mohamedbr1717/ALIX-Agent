"""Voice gateway: download Telegram voice notes, transcribe via Groq Whisper.

Stdlib only (urllib). Credentials from environment, never logged.
Fail-closed: every method returns {"ok": False, "error": ...} on failure.
"""

from __future__ import annotations

import io
import json
import os
import urllib.request
import urllib.error
import uuid

TELEGRAM_API = "https://api.telegram.org"
GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-large-v3"

NET_TIMEOUT = 60  # transcription can take a few seconds
MAX_VOICE_BYTES = 5 * 1024 * 1024  # 5 MB cap (Telegram voice notes are small)


def _tg_api(token: str, method: str) -> dict:
    """Call a Telegram Bot API GET method, return parsed JSON."""
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"Telegram API error: {e}"}


def _multipart_body(fields: dict, file_field: str, filename: str,
                    file_bytes: bytes, file_ct: str) -> tuple[bytes, str]:
    """Build a multipart/form-data body manually (stdlib only)."""
    boundary = f"----ALIXVoice{uuid.uuid4().hex}"
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        buf.write(f"{value}\r\n".encode())
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\n'.encode())
    buf.write(f"Content-Type: {file_ct}\r\n\r\n".encode())
    buf.write(file_bytes)
    buf.write(f"\r\n--{boundary}--\r\n".encode())
    return buf.getvalue(), boundary


class VoiceGateway:
    """Download + transcribe voice notes. One instance per operation."""

    def __init__(self, groq_api_key: str | None = None):
        key = (groq_api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        if not key:
            # Fall back to ~/ALIX-Agent/.env (same pattern as core/llm.py).
            try:
                from pathlib import Path
                env_file = Path.home() / "ALIX-Agent" / ".env"
                if env_file.exists():
                    try:
                        from dotenv import dotenv_values
                        key = (dotenv_values(env_file).get("GROQ_API_KEY")
                               or "").strip()
                    except ImportError:
                        for line in env_file.read_text().splitlines():
                            if line.startswith("GROQ_API_KEY="):
                                key = line.split("=", 1)[1].strip()
                                break
            except Exception:
                pass
        self.groq_api_key = key

    def download_voice(self, bot_token: str, file_id: str) -> dict:
        """Download a Telegram voice note by file_id. Returns bytes."""
        if not bot_token or not file_id:
            return {"ok": False, "error": "bot_token/file_id مطلوبان."}
        meta = _tg_api(bot_token, f"getFile?file_id={file_id}")
        if not meta.get("ok"):
            return {"ok": False,
                    "error": f"فشل جلب ملف الصوت: {meta.get('error', '?')}"}
        file_path = (meta.get("result") or {}).get("file_path", "")
        if not file_path:
            return {"ok": False, "error": "لا يوجد file_path في رد تيليغرام."}
        url = f"{TELEGRAM_API}/file/bot{bot_token}/{file_path}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read(MAX_VOICE_BYTES + 1)
            if len(data) > MAX_VOICE_BYTES:
                return {"ok": False, "error": "ملف الصوت كبير جدًا."}
            if not data:
                return {"ok": False, "error": "ملف الصوت فارغ."}
            return {"ok": True, "audio": data, "file_path": file_path}
        except Exception as e:
            return {"ok": False, "error": f"فشل تحميل الصوت: {e}"}

    def transcribe(self, audio_bytes: bytes,
                   language: str = "ar",
                   filename: str = "voice.ogg") -> dict:
        """Transcribe audio via Groq Whisper. Returns text."""
        if not self.groq_api_key:
            return {"ok": False, "error": "GROQ_API_KEY غير مضبوط."}
        if not audio_bytes:
            return {"ok": False, "error": "لا يوجد صوت للتفريغ."}
        ct = "audio/ogg"
        if filename.lower().endswith((".m4a", ".mp4")):
            ct = "audio/mp4"
        elif filename.lower().endswith(".mp3"):
            ct = "audio/mpeg"
        elif filename.lower().endswith(".wav"):
            ct = "audio/wav"
        body, boundary = _multipart_body(
            {"model": WHISPER_MODEL, "language": language,
             "response_format": "json"},
            "file", filename, audio_bytes, ct,
        )
        req = urllib.request.Request(
            GROQ_WHISPER_URL, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                # Browser UA: Groq WAF blocks default urllib UA (known issue).
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8")[:200]
            except Exception:
                detail = ""
            return {"ok": False,
                    "error": f"Whisper HTTP {e.code}: {detail}"}
        except Exception as e:
            return {"ok": False, "error": f"فشل التفريغ: {e}"}
        text = (payload.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "التفريغ فارغ."}
        return {"ok": True, "transcript": text}

    def transcribe_voice(self, bot_token: str, file_id: str,
                         language: str = "ar") -> dict:
        """One-shot: download + transcribe. Main entry point."""
        dl = self.download_voice(bot_token, file_id)
        if not dl.get("ok"):
            return dl
        result = self.transcribe(dl["audio"], language=language)
        if result.get("ok"):
            result["source"] = "voice"
        return result
