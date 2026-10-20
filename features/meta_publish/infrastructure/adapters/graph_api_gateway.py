"""Meta Graph API gateway for Facebook Page publishing (stdlib only).

Phase 1 of the meta_publish feature: text posts and photo posts to the
owner's Facebook Page via the official Graph API.

Security properties:
- Credentials come from the real environment, falling back to the
  repo-root .env file (same mechanism the live bot uses: telegram_bot.py
  reads .env via dotenv_values() into a dict and never injects it into
  os.environ, so os.environ alone is not sufficient there).
  Missing credentials fail closed.
- The access token travels only in the Authorization header — never in
  a URL, a request body, a log line or a result dict.
- Photo paths are confined to the agent workspace (~/ALIX-Agent/
  workspace, the same root Policy uses): the path is resolved, must
  stay inside that root, must be an existing regular file with an image
  extension, a hard size cap, and magic bytes matching the extension —
  all checked before any network call, so an arbitrary local file can
  never be read and shipped to Meta.
- Message/caption lengths are hard-capped; links must be http/https.
- Every call has a timeout; network and Meta errors fail closed with a
  short Arabic message. Meta error codes are mapped to actionable text.
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - optional, stdlib-only fallback
    dotenv_values = None  # type: ignore[assignment]

GRAPH_HOST = "graph.facebook.com"
DEFAULT_API_VERSION = "v26.0"
TIMEOUT_S = 30
MAX_MESSAGE_CHARS = 5000
MAX_CAPTION_CHARS = 5000
MAX_LINK_CHARS = 2048
MAX_PHOTO_BYTES = 10_000_000

_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Meta error codes worth translating (stable across versions).
_ERROR_HINTS = {
    190: "رمز الوصول منتهٍ أو غير صالح — جدّد الرمز من لوحة Meta.",
    200: "صلاحية مفقودة — تأكد من pages_manage_posts ومن أن الرمز رمز صفحة.",
    100: "وسيط غير صالح في الطلب.",
    32: "حد مؤقت من Meta — أعد المحاولة لاحقًا.",
    613: "حد معدل من Meta — أعد المحاولة لاحقًا.",
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
        # graph_api_gateway.py is at
        #   <repo>/features/meta_publish/infrastructure/adapters/
        # -> five parents up is the repo root.
        repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        data = dotenv_values(repo_root / ".env") or {}
        return str(data.get(name) or "").strip()
    except Exception:
        return ""


def _magic_matches(suffix: str, data: bytes) -> bool:
    if suffix in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".gif":
        return data.startswith(b"GIF87a") or data.startswith(b"GIF89a")
    if suffix == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


class GraphApiGateway:
    """Publishes to a Facebook Page via Meta's official Graph API."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._page_id = _resolve_env("META_PAGE_ID")
        self._token = _resolve_env("META_PAGE_ACCESS_TOKEN")
        version = _resolve_env("META_GRAPH_API_VERSION")
        self._version = version or DEFAULT_API_VERSION
        if workspace_root is None:
            workspace_root = Path.home() / "ALIX-Agent" / "workspace"
        self._workspace_root = Path(workspace_root)

    # ------------------------------------------------------------------
    # configuration / shared request plumbing
    # ------------------------------------------------------------------

    def _configured(self) -> str:
        if not self._page_id:
            return "META_PAGE_ID غير مضبوط في البيئة."
        if not self._token:
            return "META_PAGE_ACCESS_TOKEN غير مضبوط في البيئة."
        return ""

    def _send(self, request: urllib.request.Request, action: str) -> dict:
        """Run one request; return parsed JSON or an error result dict."""
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            return {
                "ok": False,
                "action": action,
                "error": self._meta_error(e),
            }
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {
                "ok": False,
                "action": action,
                "error": "تعذر الوصول إلى Meta: %s" % str(e)[:120],
            }
        except (ValueError, UnicodeDecodeError):
            return {
                "ok": False,
                "action": action,
                "error": "رد غير صالح من Meta.",
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

    # ------------------------------------------------------------------
    # text posts
    # ------------------------------------------------------------------

    def post_text(self, message: str, link: str = "") -> dict:
        action = "facebook_post_text"
        missing = self._configured()
        if missing:
            return {"ok": False, "action": action, "error": missing}
        body = message if isinstance(message, str) else ""
        if not body.strip():
            return {"ok": False, "action": action, "error": "نص المنشور فارغ."}
        if len(body) > MAX_MESSAGE_CHARS:
            return {
                "ok": False,
                "action": action,
                "error": f"المنشور أطول من الحد ({MAX_MESSAGE_CHARS} حرفًا).",
            }
        payload: dict = {"message": body}
        link = link if isinstance(link, str) else ""
        if link:
            if len(link) > MAX_LINK_CHARS or not link.startswith(
                ("https://", "http://")
            ):
                return {
                    "ok": False,
                    "action": action,
                    "error": "الرابط المرفق غير صالح (يلزم http/https).",
                }
            payload["link"] = link
        url = f"https://{GRAPH_HOST}/{self._version}/{self._page_id}/feed"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        data = self._send(req, action)
        if data.get("ok") is False:
            return data
        post_id = data.get("id")
        if post_id:
            return {
                "ok": True,
                "action": action,
                "message": "نُشر المنشور على صفحة فيسبوك.",
                "post_id": post_id,
            }
        return {"ok": False, "action": action, "error": "رد غير متوقع من Meta."}

    # ------------------------------------------------------------------
    # photo posts
    # ------------------------------------------------------------------

    def _validate_image(self, image_path: str) -> tuple[Path | None, bytes, str]:
        """Resolve + validate a workspace image. (path, bytes, error)."""
        if not isinstance(image_path, str) or not image_path.strip():
            return None, b"", "مسار الصورة فارغ."
        if "\x00" in image_path:
            return None, b"", "مسار الصورة غير صالح."
        root = self._workspace_root.resolve()
        candidate = Path(image_path.strip())
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            return None, b"", "مسار الصورة غير صالح."
        if resolved != root and root not in resolved.parents:
            return None, b"", "الصورة خارج workspace — مرفوض."
        if not resolved.is_file():
            return None, b"", "ملف الصورة غير موجود داخل workspace."
        suffix = resolved.suffix.lower()
        if suffix not in _IMAGE_CONTENT_TYPES:
            return None, b"", "امتداد الصورة غير مدعوم (jpg/png/gif/webp)."
        try:
            size = resolved.stat().st_size
        except OSError:
            return None, b"", "تعذر قراءة ملف الصورة."
        if size <= 0:
            return None, b"", "ملف الصورة فارغ."
        if size > MAX_PHOTO_BYTES:
            return None, b"", f"الصورة أكبر من الحد ({MAX_PHOTO_BYTES} بايت)."
        try:
            data = resolved.read_bytes()
        except OSError:
            return None, b"", "تعذر قراءة ملف الصورة."
        if not _magic_matches(suffix, data):
            return None, b"", "محتوى الملف لا يطابق امتداد الصورة."
        return resolved, data, ""

    def post_photo(self, image_path: str, caption: str = "") -> dict:
        action = "facebook_post_photo"
        missing = self._configured()
        if missing:
            return {"ok": False, "action": action, "error": missing}
        caption = caption if isinstance(caption, str) else ""
        if len(caption) > MAX_CAPTION_CHARS:
            return {
                "ok": False,
                "action": action,
                "error": f"التعليق أطول من الحد ({MAX_CAPTION_CHARS} حرفًا).",
            }
        resolved, data, error = self._validate_image(image_path)
        if error:
            return {"ok": False, "action": action, "error": error}
        assert resolved is not None  # for type checkers; error covers None

        boundary = "----alixmeta" + secrets.token_hex(8)
        chunks: list[bytes] = []
        if caption:
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="caption"\r\n\r\n'
                ).encode("utf-8")
            )
            chunks.append(caption.encode("utf-8"))
            chunks.append(b"\r\n")
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="source"; '
                f'filename="{resolved.name}"\r\n'
                f"Content-Type: {_IMAGE_CONTENT_TYPES[resolved.suffix.lower()]}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(data)
        chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)

        url = f"https://{GRAPH_HOST}/{self._version}/{self._page_id}/photos"
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        result = self._send(req, action)
        if result.get("ok") is False:
            return result
        post_id = result.get("post_id") or result.get("id")
        if post_id:
            return {
                "ok": True,
                "action": action,
                "message": "نُشرت الصورة على صفحة فيسبوك.",
                "post_id": post_id,
                "photo_id": result.get("id"),
            }
        return {"ok": False, "action": action, "error": "رد غير متوقع من Meta."}
