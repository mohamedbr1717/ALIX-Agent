from __future__ import annotations

import json
import os
from pathlib import Path
from dotenv import dotenv_values
import re
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from core.secret_scrub import scrub_literal as _scrub_literal

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
        timeout: int = 120,
        think_budget_chars: Optional[int] = None
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

        raw_budget = (
            think_budget_chars
            if think_budget_chars is not None
            else os.getenv("ALIX_THINK_BUDGET_CHARS")
        )
        self.think_budget_chars = self._parse_think_budget(
            raw_budget
        )

    # ============================================================
    # Local chat
    # ============================================================

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ) -> dict:

        if self.think_budget_chars:
            return self._chat_streaming(
                messages,
                tools
            )

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

            # المحتوى الفارغ = فشل صريح: عيب حلقة التفكير في
            # النماذج الصغيرة ينتج content فارغًا (احتراق الميزانية
            # أو توقف قبل </think>)، فيُعامل كفشل ليتمكن الموجّه
            # من التصعيد للنموذج البعيد. استثناء: رسائل tool_calls
            # قد تحمل content فارغًا شرعيًا فتُمرَّر كما هي.
            content = message.get("content")
            tool_calls = message.get("tool_calls")

            if not tool_calls and not (
                isinstance(content, str)
                and content.strip()
            ):

                return {
                    "role": "assistant",
                    "content": (
                        "❌ المحرك المحلي أعاد "
                        "محتوى فارغًا."
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

    # ============================================================
    # Streaming chat with a runtime think budget
    # ============================================================

    @staticmethod
    def _parse_think_budget(
        raw: Any
    ) -> Optional[int]:
        """حروف التفكير المسموحة قبل إجهاض البث.

        يُقاس عبر حقل reasoning_content المنفصل (llama-server)
        أو مقطع <think> داخل المحتوى كاحتياط.

        None/""/قيمة فاسدة → الافتراضي 4000. "0" → معطّل.
        """

        if raw is None:
            return 4000

        if isinstance(raw, str) and not raw.strip():
            return 4000

        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 4000

        return value if value > 0 else None

    @staticmethod
    def _think_len(text: str) -> int:
        """طول مقطع <think>…</think> (أو المفتوح منه) بالحروف."""

        start = text.find("<think>")

        if start == -1:
            return 0

        start += len("<think>")
        end = text.find("</think>", start)

        if end == -1:
            return len(text) - start

        return end - start

    @staticmethod
    def _think_budget_exceeded(
        budget: int,
        measured: int
    ) -> dict:
        """قاموس الفشل الموحّد عند تجاوز ميزانية التفكير."""

        return {
            "role": "assistant",
            "content": (
                "❌ تجاوز المحرك المحلي "
                "ميزانية التفكير "
                f"({measured} > {budget} حرف)."
            )
        }

    @staticmethod
    def _normalize_stream_message(
        message: dict
    ) -> dict:
        """المحتوى الفارغ = فشل صريح (مسار البث).

        نفس قاعدة chat(): رسائل tool_calls قد تحمل content
        فارغًا شرعيًا فتُمرَّر كما هي.
        """

        content = message.get("content")
        tool_calls = message.get("tool_calls")

        if not tool_calls and not (
            isinstance(content, str)
            and content.strip()
        ):

            return {
                "role": "assistant",
                "content": (
                    "❌ المحرك المحلي أعاد "
                    "محتوى فارغًا."
                )
            }

        return message

    def _request_error_dict(
        self,
        exc: Exception
    ) -> dict:
        """ترجمة أي عطل نقل إلى قاموس الفشل الموحّد."""

        if isinstance(
            exc,
            urllib.error.HTTPError
        ):

            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace"
                )[:1000]
            except Exception:
                body = ""

            text = (
                "❌ خطأ HTTP في المحرك المحلي: "
                f"{exc.code} {body}"
            )

        elif isinstance(
            exc,
            urllib.error.URLError
        ):

            text = (
                "❌ تعذر الاتصال بالمحرك المحلي: "
                f"{exc.reason}"
            )

        elif isinstance(exc, TimeoutError):

            text = "❌ انتهت مهلة المحرك المحلي."

        elif isinstance(
            exc,
            json.JSONDecodeError
        ):

            text = (
                "❌ المحرك المحلي أرسل "
                "استجابة JSON غير صالحة."
            )

        else:

            text = (
                "❌ خطأ في المحرك المحلي: "
                f"{exc}"
            )

        return {
            "role": "assistant",
            "content": text
        }

    def _chat_streaming(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ) -> dict:
        """بث SSE مع إجهاض عند تجاوز ميزانية التفكير.

        نراقب التفكير أثناء البث — أساسًا عبر حقل
        reasoning_content المنفصل الذي يبثه llama-server،
        واحتياطيًا عبر مقطع <think> داخل المحتوى لمن لا
        يفصل الحقل. عند التجاوز نغلق الاتصال فورًا ونعيد
        فشلًا صريحًا فيصعّد الموجّه للبعيد.
        """

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2048,
            "stream": True
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
                "Accept": "text/event-stream"
            },
            method="POST"
        )

        try:
            response = urllib.request.urlopen(
                request,
                timeout=self.timeout
            )
        except Exception as exc:

            return self._request_error_dict(exc)

        try:

            return self._read_stream(
                response,
                self.think_budget_chars
            )

        except Exception as exc:

            return self._request_error_dict(exc)

        finally:

            try:
                response.close()
            except Exception:
                pass

    def _read_stream(
        self,
        response: Any,
        budget: int
    ) -> dict:
        """تجميع أحداث SSE وإجهاض البث عند تجاوز الميزانية."""

        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}
        role = "assistant"
        reasoning_len = 0

        for raw_line in response:

            line = (
                raw_line.decode("utf-8", errors="replace")
                if isinstance(raw_line, bytes)
                else str(raw_line)
            ).strip()

            if not line.startswith("data:"):
                continue

            data = line[5:].strip()

            if data == "[DONE]":
                break

            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = event.get("choices") or []
            delta = (
                choices[0].get("delta")
                if choices
                else None
            ) or {}

            if not delta:
                continue

            if delta.get("role"):
                role = delta["role"]

            # حقل التفكير المنفصل (llama-server:
            # reasoning_content).
            reasoning = (
                delta.get("reasoning_content")
                or delta.get("reasoning")
            )

            if isinstance(reasoning, str) and reasoning:
                reasoning_len += len(reasoning)

                if reasoning_len > budget:
                    return self._think_budget_exceeded(
                        budget,
                        reasoning_len
                    )

            piece = delta.get("content")

            if piece:
                content_parts.append(piece)

                # احتياط: وسوم <think> لمن لا يفصل حقل
                # التفكير.
                think_len = self._think_len(
                    "".join(content_parts)
                )

                if think_len > budget:
                    return self._think_budget_exceeded(
                        budget,
                        think_len
                    )

            for call in delta.get("tool_calls") or []:
                index = call.get("index", 0)
                slot = tool_calls.setdefault(
                    index,
                    {
                        "id": call.get("id", ""),
                        "type": call.get("type", "function"),
                        "function": {
                            "name": "",
                            "arguments": ""
                        }
                    }
                )

                if call.get("id"):
                    slot["id"] = call["id"]

                func = call.get("function") or {}

                if func.get("name"):
                    slot["function"]["name"] = func["name"]

                if func.get("arguments"):
                    slot["function"]["arguments"] += func[
                        "arguments"
                    ]

        message: dict[str, Any] = {
            "role": role,
            "content": "".join(content_parts)
        }

        if tool_calls:
            message["tool_calls"] = [
                tool_calls[index]
                for index in sorted(tool_calls)
            ]

        return self._normalize_stream_message(message)


class HybridLLM:
    """
    محرك LLM هجين:

        Remote (OpenRouter / Groq)
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

    # مزودو الخدمة البعيدة المدعومون.
    # يُختار المزود عبر REMOTE_PROVIDER
    # (openrouter افتراضيًا).
    # Groq: طبقة مجانية دائمة بدون بطاقة بنكية.
    REMOTE_PROVIDERS = {
        "openrouter": {
            "label": "OpenRouter",
            "base_url": (
                "https://openrouter.ai/api/v1"
            ),
            "key_var": "OPENROUTER_API_KEY",
            "model_var": "OPENROUTER_MODEL",
            "default_model": (
                DEFAULT_REMOTE_MODEL
            ),
        },
        "groq": {
            "label": "Groq",
            "base_url": (
                "https://api.groq.com/openai/v1"
            ),
            "key_var": "GROQ_API_KEY",
            "model_var": "GROQ_MODEL",
            "default_model": (
                "llama-3.3-70b-versatile"
            ),
        },
    }

    def __init__(
        self,
        use_remote: bool = True,
        max_retries: int = 3
    ):

        self.use_remote = bool(
            use_remote
        )

        self.max_retries = max(
            0,
            int(max_retries)
        )

        self.local = LocalLLM()

        # Load credentials without modifying os.environ.
        env_file = (
            Path.home()
            / "ALIX-Agent"
            / ".env"
        )
        file_env = dotenv_values(env_file)

        provider_name = (
            file_env.get("REMOTE_PROVIDER")
            or os.getenv(
                "REMOTE_PROVIDER",
                "openrouter"
            )
        ).strip().lower()

        if provider_name not in self.REMOTE_PROVIDERS:

            provider_name = "openrouter"

        self.provider = provider_name

        provider_cfg = self.REMOTE_PROVIDERS[
            self.provider
        ]

        self.remote_label = provider_cfg[
            "label"
        ]

        self.api_key = (
            file_env.get(provider_cfg["key_var"])
            or os.getenv(provider_cfg["key_var"])
        )

        self.model = (
            file_env.get(provider_cfg["model_var"])
            or os.getenv(
                provider_cfg["model_var"],
                provider_cfg["default_model"]
            )
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
                    base_url=provider_cfg[
                        "base_url"
                    ],
                    timeout=90.0,
                    max_retries=0
                )

            except Exception:

                self.client = None
                self.use_remote = False

        else:

            self.use_remote = False


    def _fresh_client(self):
        """عميل جديد لكل طلب — يتجنب connection pool العالق."""
        from openai import OpenAI

        provider_cfg = self.REMOTE_PROVIDERS[self.provider]
        return OpenAI(
            api_key=self.api_key,
            base_url=provider_cfg["base_url"],
            timeout=90.0,
            max_retries=0,
        )

    # ============================================================
    # Safe error text
    # ============================================================

    def _rate_limit_wait(self, exc: Exception) -> float | None:
        """استخرج مدة الانتظار المقترحة من خطأ 429 (إن وُجدت)."""
        text = str(exc)
        if "429" not in text and "rate_limit" not in text.lower():
            return None
        m = re.search(r"try again in ([\d.]+)s", text)
        if m:
            try:
                return float(m.group(1)) + 0.5  # هامش أمان
            except ValueError:
                pass
        return None

    def _safe_error(
        self,
        error: Exception
    ) -> str:

        text = str(error)

        # منع ظهور المفتاح في الرسائل.
        # يعتمد على المفتاح المخزن داخل HybridLLM
        # وليس على os.environ.
        # Unified in core/secret_scrub.py (single source of truth).
        text = _scrub_literal(text, [self.api_key or ""])

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
                f"{self.remote_label} غير مهيأ."
            )

        # ALIX native context compression: reduce tokens before sending.
        # Fail-closed: on error, sends original messages.
        try:
            from core.context_compressor import ContextCompressor
            _compressor = ContextCompressor(max_tokens=6000)
            messages = _compressor.compress(messages)
        except Exception:
            pass

        # Tool calls need short outputs — lower the token budget to
        # stay under Groq's TPM rate limit.
        _max_tokens = 1024 if tools else 4096
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": _max_tokens
        }

        if tools:

            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # بعض نماذج OpenRouter قد تدعم reasoning_effort،
        # ولكن عدم تمريره افتراضيًا أكثر توافقًا.
        try:

            return self._fresh_client().chat.completions.create(
                **kwargs
            )

        except Exception:

            # محاولة ثانية بدون max_completion_tokens
            # إذا رفض المزود هذا الحقل.
            kwargs.pop(
                "max_completion_tokens",
                None
            )

            return self._fresh_client().chat.completions.create(
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
                            f"{self.remote_label} أرسل استجابة "
                            "بدون choices."
                        )

                    message = choices[0].message

                    return message

                except Exception as exc:

                    last_error = exc

                    if attempt < self.max_retries:

                        # 429: احترم مدة الانتظار المقترحة من Groq.
                        wait = self._rate_limit_wait(exc)
                        if wait is not None:
                            delay = min(wait, 30)
                        else:
                            delay = min(
                                2 ** (attempt + 1),
                                10
                            )

                        time.sleep(delay)

            print(
                f"⚠️ فشل {self.remote_label} بعد "
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
            "remote_provider": self.provider,
            "remote_configured": bool(
                self.api_key
            ),
            "remote_model": self.model,
            "local_url": self.local.url,
            "local_model": self.local.model
        }
