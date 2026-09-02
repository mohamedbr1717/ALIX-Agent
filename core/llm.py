from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from openai import OpenAI


class LocalLLM:
    """
    محرك LLM محلي متوافق مع OpenAI-compatible API
    مثل llama.cpp server.

    الافتراضي:
        http://127.0.0.1:8081/v1/chat/completions
    """

    def __init__(
        self,
        url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 120
    ):

        self.url = (
            url
            or os.getenv(
                "ALIX_LOCAL_LLM_URL",
                "http://127.0.0.1:8081/v1/chat/completions"
            )
        )

        self.model = (
            model
            or os.getenv(
                "ALIX_LOCAL_MODEL",
                "Qwen3.5-4B-Instruct-Q4_K_M.gguf"
            )
        )

        self.timeout = max(
            10,
            int(timeout)
        )

    # ============================================================
    # Local chat
    # ============================================================

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ) -> dict:

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2048
        }

        if tools:

            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = json.dumps(
            payload,
            ensure_ascii=False
        ).encode("utf-8")

        request = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            method="POST"
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=self.timeout
            ) as response:

                raw = response.read().decode(
                    "utf-8",
                    errors="replace"
                )

                result = json.loads(raw)

            choices = result.get(
                "choices",
                []
            )

            if not choices:

                return {
                    "role": "assistant",
                    "content": (
                        "❌ المحرك المحلي لم يُرجع "
                        "أي اختيار صالح."
                    )
                }

            message = choices[0].get(
                "message"
            )

            if not isinstance(
                message,
                dict
            ):

                return {
                    "role": "assistant",
                    "content": (
                        "❌ استجابة المحرك المحلي "
                        "غير صالحة."
                    )
                }

            return message

        except urllib.error.HTTPError as exc:

            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace"
                )[:1000]
            except Exception:
                body = ""

            return {
                "role": "assistant",
                "content": (
                    "❌ خطأ HTTP في المحرك المحلي: "
                    f"{exc.code} {body}"
                )
            }

        except urllib.error.URLError as exc:

            return {
                "role": "assistant",
                "content": (
                    "❌ تعذر الاتصال بالمحرك المحلي: "
                    f"{exc.reason}"
                )
            }

        except TimeoutError:

            return {
                "role": "assistant",
                "content": (
                    "❌ انتهت مهلة المحرك المحلي."
                )
            }

        except json.JSONDecodeError:

            return {
                "role": "assistant",
                "content": (
                    "❌ المحرك المحلي أرسل "
                    "استجابة JSON غير صالحة."
                )
            }

        except Exception as exc:

            return {
                "role": "assistant",
                "content": (
                    "❌ خطأ في المحرك المحلي: "
                    f"{exc}"
                )
            }


class HybridLLM:
    """
    محرك LLM هجين:

        OpenRouter
             ↓
        Retry
             ↓
        Local LLM

    إذا فشل الاتصال بالخدمة البعيدة،
    يتم التحويل تلقائيًا إلى المحرك المحلي.
    """

    DEFAULT_REMOTE_MODEL = (
        "openai/gpt-oss-120b"
    )

    def __init__(
        self,
        use_remote: bool = True,
        max_retries: int = 2
    ):

        self.use_remote = bool(
            use_remote
        )

        self.max_retries = max(
            0,
            int(max_retries)
        )

        self.local = LocalLLM()

        self.api_key = os.getenv(
            "OPENROUTER_API_KEY"
        )

        self.model = os.getenv(
            "OPENROUTER_MODEL",
            self.DEFAULT_REMOTE_MODEL
        )

        self.client: Optional[
            OpenAI
        ] = None

        if (
            self.use_remote
            and self.api_key
        ):

            try:

                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=(
                        "https://openrouter.ai/api/v1"
                    ),
                    timeout=90.0,
                    max_retries=0
                )

            except Exception:

                self.client = None
                self.use_remote = False

        else:

            self.use_remote = False

    # ============================================================
    # Safe error text
    # ============================================================

    @staticmethod
    def _safe_error(
        error: Exception
    ) -> str:

        text = str(error)

        # منع ظهور المفتاح في الرسائل.
        sensitive = [
            os.getenv(
                "OPENROUTER_API_KEY",
                ""
            )
        ]

        for secret in sensitive:

            if secret:
                text = text.replace(
                    secret,
                    "***REDACTED***"
                )

        return text[:1000]

    # ============================================================
    # Remote call
    # ============================================================

    def _remote_chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]]
    ):

        if not self.client:

            raise RuntimeError(
                "OpenRouter غير مهيأ."
            )

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": 4096
        }

        if tools:

            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # بعض نماذج OpenRouter قد تدعم reasoning_effort،
        # ولكن عدم تمريره افتراضيًا أكثر توافقًا.
        try:

            return self.client.chat.completions.create(
                **kwargs
            )

        except Exception:

            # محاولة ثانية بدون max_completion_tokens
            # إذا رفض المزود هذا الحقل.
            kwargs.pop(
                "max_completion_tokens",
                None
            )

            return self.client.chat.completions.create(
                **kwargs
            )

    # ============================================================
    # Chat
    # ============================================================

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ):

        # --------------------------------------------------------
        # Remote
        # --------------------------------------------------------

        if (
            self.use_remote
            and self.client
        ):

            last_error = None

            for attempt in range(
                self.max_retries + 1
            ):

                try:

                    response = self._remote_chat(
                        messages,
                        tools
                    )

                    choices = getattr(
                        response,
                        "choices",
                        None
                    )

                    if not choices:

                        raise RuntimeError(
                            "OpenRouter أرسل استجابة "
                            "بدون choices."
                        )

                    message = choices[0].message

                    return message

                except Exception as exc:

                    last_error = exc

                    if attempt < self.max_retries:

                        delay = min(
                            2 ** attempt,
                            5
                        )

                        time.sleep(delay)

            print(
                "⚠️ فشل OpenRouter بعد "
                f"{self.max_retries + 1} محاولة."
            )

            print(
                "   السبب:",
                self._safe_error(
                    last_error
                )
            )

            print(
                "🔄 التحويل إلى المحرك المحلي..."
            )

        # --------------------------------------------------------
        # Local fallback
        # --------------------------------------------------------

        return self.local.chat(
            messages,
            tools
        )

    # ============================================================
    # Status
    # ============================================================

    def status(self) -> dict:

        return {
            "remote_enabled": self.use_remote,
            "remote_configured": bool(
                self.api_key
            ),
            "remote_model": self.model,
            "local_url": self.local.url,
            "local_model": self.local.model
        }
