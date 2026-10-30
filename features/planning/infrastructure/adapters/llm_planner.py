"""LLM planner adapter: PlannerPort over the existing DualLLM.

Routing, sensitivity and the 7500-token budget guard are all
inherited from the router as-is (spec §4.6): a plan drafted over
sensitive content routes locally by the router's current rules,
with no override here. This adapter only shapes prompts and
parses the reply; a reply that is not valid JSON becomes an
empty dict, which domain validation rejects — a bad draft can
never become a stored plan.
"""
from __future__ import annotations

import json
import re
from typing import List

from domain.planning.entities import PlanStep, PriorAction

from features.planning.application.ports.planner import PlannerPort

_PLAN_SYSTEM = """أنت مخطّط مهام داخل وكيل ALIX. حوّل الهدف إلى خطة خطوات قابلة للتنفيذ بالأدوات المتاحة فقط.
أعد JSON فقط، دون أي شرح أو تنسيق markdown، بالشكل التالي حرفيًا:
{"steps": [{"intent": "وصف قصير للخطوة بلغة المستخدم", "tool": "اسم الأداة", "args": {}}]}
قواعد صارمة:
- استخدم فقط أسماء الأدوات المدرجة، وفقط مفاتيح وسائط مسموحة لكل أداة.
- كل خطوة كائن بمفاتيح intent و tool و args فقط — لا تضف أي مفتاح آخر (لا معرّفات ولا حالات ولا أزمنة).
- استثناء وحيد (قرار 2): مفتاح verify اختياري لمواصفة تحقق بالقراءة الراجعة، بالشكل {"read_tool": "أداة قراءة فقط", "args": {}, "predicate": "field_equals" أو "exists_matching" أو "absent_matching", "params": {}}، أو {"channel": "memory", ...} لحالة الذاكرة الداخلية. القوالب {{step.args.X}} و{{step.result.Y}} مسموحة داخل قيمه. لا تستخدمه إلا حين لا تكفي المواصفة الافتراضية للأداة.
- الخطوات مرتبة بترتيب التنفيذ، ولا تعتمد خطوة على نص حر من نتيجة خطوة سابقة إلا عبر وسائط صريحة.
- إن كان الهدف خطوة واحدة أعد خطوة واحدة فقط."""

_DECOMPOSE_SYSTEM = """أنت مخطّط مهام داخل وكيل ALIX. فشلت خطوة من خطة جارية؛ قرّر واحدًا من ثلاثة ردود JSON فقط، دون شرح:
{"mode": "decompose", "steps": [{"intent": "...", "tool": "...", "args": {}}]} — قسّم الخطوة الفاشلة إلى خطوات فرعية أبسط (4 كحد أقصى).
{"mode": "rewrite_tail", "steps": [{"intent": "...", "tool": "...", "args": {}}]} — استبدل الخطوات المتبقية بخطة ذيل جديدة.
{"mode": "give_up"} — لا بديل آمن.
استخدم فقط الأدوات المدرجة ومفاتيح وسائطها المسموحة، وكل خطوة بمفاتيح intent و tool و args فقط (ومفتاح verify اختياري بشروط خطة الإنشاء نفسها)."""


def _extract_text(response) -> str:
    """Mirror of the agent's message_content handling: SDK
    message objects, plain dicts, and choices-shaped dicts."""
    if response is None:
        return ""
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(response, dict):
        text = response.get("content")
        if isinstance(text, str):
            return text
        choices = response.get("choices") or []
        if choices:
            first = choices[0]
            message = (
                first.get("message", {})
                if isinstance(first, dict)
                else getattr(first, "message", None)
            )
            if isinstance(message, dict):
                return message.get("content") or ""
            return getattr(message, "content", "") or ""
    return ""


def _parse_draft(text: str) -> dict:
    cleaned = re.sub(
        r"<think>.*?</think>", "", text or "", flags=re.DOTALL
    ).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```[a-zA-Z]*\s*", "", cleaned
        )
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class LLMPlannerAdapter(PlannerPort):
    """PlannerPort backed by the agent's routed LLM client."""

    def __init__(self, llm):
        # DualLLM-shaped: chat(messages, tools=None).
        self._llm = llm

    # ---------------------------------------------------------

    def plan(
        self,
        goal: str,
        prior_actions: List[PriorAction],
        context: dict,
    ) -> dict:
        tools_listing = json.dumps(
            context.get("tool_args", {}),
            ensure_ascii=False,
            sort_keys=True,
        )
        prior = "\n".join(
            f"- {p.tool} ({p.args_hash[:8]}): {p.result_ref}"
            for p in prior_actions
        )
        user = (
            f"الهدف: {goal}\n\n"
            f"الأدوات المتاحة ومفاتيح وسائطها: {tools_listing}\n"
        )
        if prior:
            user += (
                "\nما نُفّذ أصلًا تفاعليًا قبل التخطيط "
                f"(لا تكرّره):\n{prior}\n"
            )
        user += "\nأعد خطة للعمل المتبقي فقط."

        response = self._llm.chat(
            [
                {"role": "system", "content": _PLAN_SYSTEM},
                {"role": "user", "content": user},
            ],
            tools=None,
        )
        return _parse_draft(_extract_text(response))

    def decompose(
        self,
        goal: str,
        failed_step: PlanStep,
        remaining_steps: List[PlanStep],
    ) -> dict:
        remaining = "\n".join(
            f"- {s.step_id}: {s.intent} ({s.tool})"
            for s in remaining_steps
        )
        user = (
            f"الهدف: {goal}\n\n"
            f"الخطوة الفاشلة: {failed_step.intent} "
            f"(الأداة: {failed_step.tool}, "
            f"الوسائط: {json.dumps(failed_step.args, ensure_ascii=False, default=str)})\n"
            f"سبب الفشل: {failed_step.error or 'غير معروف'}\n\n"
            f"الخطوات المتبقية:\n{remaining or '(لا شيء)'}"
        )

        response = self._llm.chat(
            [
                {
                    "role": "system",
                    "content": _DECOMPOSE_SYSTEM,
                },
                {"role": "user", "content": user},
            ],
            tools=None,
        )
        return _parse_draft(_extract_text(response))
