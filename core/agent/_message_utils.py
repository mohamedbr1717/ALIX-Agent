"""ALIXAgent _MessageUtilsMixin (private)."""
from __future__ import annotations

import json
import re
class _MessageUtilsMixin:
    """Methods moved verbatim."""

    _ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


    _BIDI_CONTROL_CHARS = (
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # LRE/RLE/PDF/LRO/RLO
        "\u2066", "\u2067", "\u2068", "\u2069",              # LRI/RLI/FSI/PDI
    )


    def extract_tool_calls(
        self,
        message
    ) -> list[tuple[str, str, dict]]:

        calls = []

        # OpenAI-compatible object
        if hasattr(message, "tool_calls"):

            tool_calls = message.tool_calls or []

            for index, call in enumerate(
                tool_calls
            ):

                try:

                    function = call.function

                    raw_arguments = (
                        function.arguments
                    )

                    if isinstance(
                        raw_arguments,
                        str
                    ):
                        arguments = json.loads(
                            raw_arguments
                        )
                    else:
                        arguments = raw_arguments

                    if not isinstance(
                        arguments,
                        dict
                    ):
                        continue

                    calls.append(
                        (
                            getattr(
                                call,
                                "id",
                                f"call-{index}"
                            ),
                            function.name,
                            arguments
                        )
                    )

                except Exception:
                    continue

            if calls:
                return calls

        # Dict-compatible object
        if isinstance(message, dict):

            raw_calls = message.get(
                "tool_calls"
            )

            if raw_calls:

                for index, call in enumerate(
                    raw_calls
                ):

                    try:

                        function = call.get(
                            "function",
                            {}
                        )

                        raw_arguments = function.get(
                            "arguments",
                            {}
                        )

                        if isinstance(
                            raw_arguments,
                            str
                        ):
                            arguments = json.loads(
                                raw_arguments
                            )
                        else:
                            arguments = raw_arguments

                        if not isinstance(
                            arguments,
                            dict
                        ):
                            continue

                        calls.append(
                            (
                                call.get(
                                    "id",
                                    f"call-{index}"
                                ),
                                function.get(
                                    "name"
                                ),
                                arguments
                            )
                        )

                    except Exception:
                        continue

                if calls:
                    return calls

            # fallback format
            content = (
                message.get(
                    "content",
                    ""
                )
                or ""
            )

            pattern = (
                r"<tool_call>\s*"
                r"(\{.*?\})"
                r"\s*</tool_call>"
            )

            for index, match in enumerate(
                re.findall(
                    pattern,
                    content,
                    flags=re.DOTALL
                )
            ):

                try:

                    obj = json.loads(match)

                    name = obj.get(
                        "name"
                    )

                    arguments = obj.get(
                        "arguments",
                        {}
                    )

                    if isinstance(
                        arguments,
                        str
                    ):
                        arguments = json.loads(
                            arguments
                        )

                    calls.append(
                        (
                            f"fallback-{index}",
                            name,
                            arguments
                        )
                    )

                except Exception:
                    continue

        return calls


    @staticmethod
    def message_content(
        message
    ) -> str:

        if hasattr(
            message,
            "content"
        ):
            return (
                message.content
                or ""
            )

        if isinstance(
            message,
            dict
        ):
            return (
                message.get(
                    "content",
                    ""
                )
                or ""
            )

        return ""


    def normalize_assistant_message(
        self,
        message
    ) -> dict:

        if hasattr(
            message,
            "model_dump"
        ):
            # CLEAN_TOOL_MESSAGE: نبني رسالة نظيفة بالحقول المدعومة فقط.
            # model_dump() الكامل يحوي حقولًا يرفضها Groq (annotations, ...).
            try:
                raw = message.model_dump()
            except Exception:
                raw = {}
            data = {"role": "assistant"}
            content = raw.get("content")
            # content قد يكون None مع tool_calls — نحتفظ به كما هو.
            data["content"] = content
            tool_calls = raw.get("tool_calls")
            if tool_calls:
                # تنظيف كل tool_call للحقول الأساسية فقط.
                clean_calls = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc.get("function", {})
                        clean_calls.append(
                            {
                                "id": tc.get("id"),
                                "type": tc.get("type", "function"),
                                "function": {
                                    "name": fn.get("name"),
                                    "arguments": fn.get("arguments"),
                                },
                            }
                        )
                    else:
                        # كائن — نحوّله عبر model_dump جزئي.
                        try:
                            tcd = tc.model_dump() if hasattr(tc, "model_dump") else {}
                        except Exception:
                            tcd = {}
                        fn = tcd.get("function", {}) or {}
                        clean_calls.append(
                            {
                                "id": tcd.get("id"),
                                "type": tcd.get("type", "function"),
                                "function": {
                                    "name": fn.get("name"),
                                    "arguments": fn.get("arguments"),
                                },
                            }
                        )
                data["tool_calls"] = clean_calls

        elif isinstance(
            message,
            dict
        ):
            data = dict(message)

        else:
            data = {
                "role": "assistant",
                "content": self.message_content(
                    message
                )
            }

        # GROQ_SANITIZE_V2: إسقاط الحقول غير المدعومة من المزوّد
        # (مثل annotations) — Groq يرفض الطلب (400) عند وجودها في
        # رسالة assistant فيسقط الوكيل بصمت إلى المحلي البطيء.
        # حذف فقط (fail-closed): لا إضافة ولا تعديل للقيم المبقاة.
        _allowed = {"role", "content", "name", "tool_calls", "function_call"}
        data = {k: v for k, v in data.items() if k in _allowed}
        _tool_calls = data.get("tool_calls")
        if isinstance(_tool_calls, list):
            _clean_calls = []
            for _tc in _tool_calls:
                if not isinstance(_tc, dict):
                    continue
                _entry = {
                    k: v for k, v in _tc.items()
                    if k in {"id", "type", "function"}
                }
                _fn = _entry.get("function")
                if isinstance(_fn, dict):
                    _entry["function"] = {
                        k: v for k, v in _fn.items()
                        if k in {"name", "arguments"}
                    }
                _clean_calls.append(_entry)
            data["tool_calls"] = _clean_calls
        data["role"] = "assistant"

        # Groq يرفض function_call=null — نحذفه إن كان فارغًا.
        # (tool_calls هو الحقل الحديث المستخدم.)
        if data.get("function_call") is None:
            data.pop("function_call", None)

        return data


    @classmethod
    def _safe_display(cls, value) -> str:
        text = value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False
        )
        text = cls._ANSI_ESCAPE_RE.sub("", text)
        for char in cls._BIDI_CONTROL_CHARS:
            text = text.replace(char, "")
        # Drop other C0 control chars except newline/tab, which are
        # harmless for display purposes here.
        text = "".join(
            ch for ch in text
            if ch in ("\n", "\t") or ch >= " "
        )
        if len(text) > 2000:
            text = text[:2000] + "...[TRUNCATED]"
        return text


