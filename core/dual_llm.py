"""Dual-LLM router: task routing + sensitivity gating.

يجمع نموذجًا بعيدًا قويًا ونموذجًا محليًا ضعيفًا في قرار توجيه
واحد حتمي، يُطبَّق على كل استدعاء LLM:

    1. حساسية المحتوى (أعلى أولوية):
       sensitive=True صريحًا، أو كشف تلقائي لأسرار عالية الثقة
       (مفاتيح API، كلمات سر، tokens) → المحلي فقط، ولا يغادر
       الجهاز أبدًا. إن تعذّر المحلي → رفض fail-closed، بلا
       تصعيد للبعيد.
    2. استدعاء الأدوات (tools is not None):
       → البعيد (تنسيق الأدوات يحتاج النموذج القوي).
    3. تلميح مهمة محدودة task في LOCAL_TASKS:
       → المحلي (مهام صغيرة مغلقة: تلخيص/استخراج/صياغة/تصنيف).
       إن فشل المحلي → تصعيد للبعيد (معالجة ضعف النموذج المحلي:
       الضعيف يحاول حيث يكفي، والقوي يلتقط فشله).
    4. الافتراضي → البعيد (يحافظ على السلوك الحالي).

لا توجد heuristics صامتة (مثل طول الرسالة): التوجيه للمحلي
يتطلب تلميحًا صريحًا أو حساسية مكتشفة. صريح > سحري.

الكشف التلقائي للحساسية ضيّق عمدًا: الأسرار فقط. بيانات PII
العادية (أسماء، إيميلات، هواتف) لا تُكتشف تلقائيًا — من يعرف
أن المحتوى حساس يمرّر sensitive=True صريحًا.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from core.llm import HybridLLM, LocalLLM


# ============================================================
# Routing policy
# ============================================================

#: مهام محدودة يُسمح للمحلي بخدمتها، عبر task= صريح فقط.
#: تُوسَّع بعد تدريب LoRA عندما يثبت المحلي كفاءته (مهام
#: الكريبتو/الكود مثلًا).
LOCAL_TASKS = frozenset(
    {
        "summarize",
        "extract",
        "format",
        "classify",
    }
)

#: علامات أسرار عالية الثقة. تُفحص في نص كل رسالة.
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"gho_[A-Za-z0-9]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"xox[bap]-[A-Za-z0-9-]{8,}"),
    re.compile(
        r"(?i)\bapi[_-]?key\s*[:=]\s*\S+"
    ),
    re.compile(
        r"(?i)\bpassword\s*[:=]\s*\S+"
    ),
    re.compile(
        r"(?i)\bpasswd\s*[:=]\s*\S+"
    ),
    re.compile(
        r"(?i)\bsecret\s*[:=]\s*\S+"
    ),
    re.compile(
        r"(?i)\btoken\s*[:=]\s*\S+"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    ),
)


def _message_texts(
    messages: Any,
):
    """يستخرج كل النصوص من الرسائل، مهما كان شكل المحتوى."""

    if not messages:
        return

    for message in messages:

        content = (
            message.get("content", "")
            if isinstance(message, dict)
            else message
        )

        if isinstance(content, str):
            yield content

        elif isinstance(content, list):

            for part in content:

                if isinstance(part, str):
                    yield part

                elif isinstance(part, dict):

                    text = part.get("text")

                    if isinstance(text, str):
                        yield text

        elif content is not None:
            yield str(content)


def detect_sensitive(
    messages: Any,
) -> bool:
    """True إن حملت أي رسالة علامة سر عالية الثقة."""

    for text in _message_texts(messages):

        for pattern in _SECRET_PATTERNS:

            if pattern.search(text):
                return True

    return False


def route(
    messages: Any,
    tools: Optional[list] = None,
    task: Optional[str] = None,
    sensitive: bool = False,
) -> tuple[str, str]:
    """قرار توجيه حتمي خالص → (engine, reason).

    engine واحد من "local" | "remote".
    """

    is_sensitive = bool(sensitive) or detect_sensitive(
        messages
    )

    if is_sensitive:
        return (
            "local",
            "sensitive: never leaves the device",
        )

    if tools:
        return (
            "remote",
            "tool orchestration needs the strong model",
        )

    if task in LOCAL_TASKS:
        return (
            "local",
            f"bounded subtask: {task}",
        )

    return (
        "remote",
        "default: preserve current behavior",
    )


# ============================================================
# DualLLM
# ============================================================

#: رسالة الرفض عند تعذّر خدمة محتوى حساس محليًا.
FAIL_CLOSED_REFUSAL = (
    "❌ تعذّر إنجاز المهمة الحساسة محليًا، "
    "ولن تُرسل إلى أي نموذج بعيد."
)


class DualLLM:
    """موجّه dual-LLM: نفس واجهة chat() الحالية + توجيه.

    - المسار البعيد يعيد استخدام HybridLLM كما هو
      (retry + تحويل تلقائي للمحلي عند فشل البعيد).
    - المسار المحلي يستدعي LocalLLM مباشرة.
    - كل قرار توجيه يُسجَّل عبر audit_fn إن وُجد (القرار
      والسبب فقط — بلا محتوى الرسائل).
    """

    def __init__(
        self,
        use_remote: bool = True,
        max_retries: int = 2,
        local: Optional[LocalLLM] = None,
        hybrid: Optional[HybridLLM] = None,
        audit_fn: Optional[
            Callable[[str, dict], Any]
        ] = None,
    ):

        self.local = (
            local if local is not None else LocalLLM()
        )

        self.hybrid = (
            hybrid
            if hybrid is not None
            else HybridLLM(
                use_remote=use_remote,
                max_retries=max_retries,
            )
        )

        self.audit_fn = audit_fn

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    def _audit(
        self,
        event: str,
        data: dict,
    ) -> None:

        if self.audit_fn is None:
            return

        try:
            self.audit_fn(event, data)
        except Exception:
            pass

    @staticmethod
    def _failed(result: Any) -> bool:
        """LocalLLM لا يرمي أبدًا: الفشل قاموس بمحتوى يبدأ بـ ❌."""

        try:
            content = result.get("content", "")
        except AttributeError:
            return True

        return (
            isinstance(content, str)
            and content.startswith("❌")
        )

    # --------------------------------------------------------
    # Chat
    # --------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        *,
        task: Optional[str] = None,
        sensitive: bool = False,
    ) -> dict:

        engine, reason = route(
            messages,
            tools=tools,
            task=task,
            sensitive=sensitive,
        )

        is_sensitive = reason.startswith(
            "sensitive"
        )

        self._audit(
            "llm_route",
            {
                "engine": engine,
                "reason": reason,
                "task": task,
                "sensitive": is_sensitive,
                "has_tools": bool(tools),
            },
        )

        if engine == "remote":
            return self.hybrid.chat(
                messages,
                tools,
            )

        # ----------------------------------------------------
        # المسار المحلي
        # ----------------------------------------------------

        result = self.local.chat(
            messages,
            tools,
        )

        if not self._failed(result):
            return result

        if is_sensitive:
            # fail-closed: المحتوى الحساس لا يُصعَّد للبعيد أبدًا.
            self._audit(
                "llm_route_fail_closed",
                {"reason": reason},
            )

            return {
                "role": "assistant",
                "content": FAIL_CLOSED_REFUSAL,
            }

        # معالجة ضعف النموذج المحلي: تصعيد للنموذج القوي.
        self._audit(
            "llm_route_escalated",
            {"reason": reason},
        )

        return self.hybrid.chat(
            messages,
            tools,
        )

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    def status(self) -> dict:

        info = self.hybrid.status()

        info.update(
            {
                "router": "dual",
                "local_tasks": sorted(LOCAL_TASKS),
                "local_url": getattr(
                    self.local, "url", None
                ),
                "local_model": getattr(
                    self.local, "model", None
                ),
            }
        )

        return info
