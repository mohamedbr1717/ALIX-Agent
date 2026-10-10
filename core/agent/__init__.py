"""ALIXAgent facade (public API unchanged)."""
from __future__ import annotations

import re
from pathlib import Path

from core.dual_llm import DualLLM
from core.policy import Policy
from core.memory import Memory
from core.executor import SafeExecutor
from core.observability import ObservabilityLogger
from core.feature_bridge import build_migrated_tool_handlers
from .prompts import SYSTEM_PROMPT, TOOLS, EVIDENCE_PRIORITY_ADDENDUM
from ._tool_pipeline import _ToolPipelineMixin
from ._message_utils import _MessageUtilsMixin
from ._context import _ContextMixin
from ._audit import _AuditMixin

class ALIXAgent(
    _ToolPipelineMixin,
    _MessageUtilsMixin,
    _ContextMixin,
    _AuditMixin,
):
    """The main executive agent. Public API unchanged."""

    MAX_ROUNDS = 8
    MAX_TOOL_CALLS_PER_ROUND = 4
    MAX_CONTEXT_CHARS = 30000
    MAX_MEMORY_CONTEXT_CHARS = 8000


    def __init__(self):
        self.policy = Policy()
        self.memory = Memory()
        self.executor = SafeExecutor(policy=self.policy)

        # الأدوات المُهاجَرة لشرائح features/ الجديدة -- تُبنى مرة
        # واحدة هنا، لا في كل استدعاء داخل _execute_tool_body.
        self._migrated_handlers = build_migrated_tool_handlers(
            self.policy,
            self.memory,
        )

        self.llm = DualLLM(
            use_remote=True,
            audit_fn=self.audit,
        )

        self.messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        ]

        self.audit_log = (
            Path.home()
            / "ALIX-Agent"
            / "logs"
            / "audit.jsonl"
        )

        self.audit_log.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.observability = ObservabilityLogger(
            self.audit_log
        )

        # Correlation ID for the currently running user request.
        self.current_request_id = None

        # Tools denied (timeout/refusal) in the current turn: confirm_tool
        # structurally blocks re-carding them until the next user message.
        self._denied_this_turn: set[str] = set()


    def run(
        self,
        user_input: str
    ) -> str:

        if not isinstance(
            user_input,
            str
        ):
            return "❌ الإدخال غير صالح."

        user_input = user_input.strip()

        if not user_input:
            return "❌ لم يتم إدخال طلب."

        self.current_request_id = (
            self.observability.new_id()
        )

        # New turn: past denials no longer block re-asking.
        self._denied_this_turn = set()

        self.messages[0] = {
            "role": "system",
            "content": self.build_system_message()
        }

        self.messages.append(
            {
                "role": "user",
                "content": user_input
            }
        )

        self.memory.add_history(
            "user",
            user_input
        )

        self.audit(
            "user_request",
            {
                "length": len(user_input)
            }
        )

        for round_number in range(
            self.MAX_ROUNDS
        ):

            self.audit(
                "agent_round",
                {
                    "round": round_number + 1
                }
            )

            self._apply_context_boundary()

            response = self.llm.chat(
                self.messages,
                tools=TOOLS
            )

            tool_calls = self.extract_tool_calls(
                response
            )

            # ----------------------------------------------------
            # Final answer
            # ----------------------------------------------------

            if not tool_calls:

                content = self.message_content(
                    response
                )

                clean_text = re.sub(
                    r"<think>.*?</think>",
                    "",
                    content or "",
                    flags=re.DOTALL
                ).strip()

                if not clean_text:
                    clean_text = (
                        "لم يُرجع النموذج نتيجة نصية."
                    )

                self.messages.append(
                    {
                        "role": "assistant",
                        "content": clean_text
                    }
                )

                self.memory.add_history(
                    "assistant",
                    clean_text
                )

                self.audit(
                    "agent_final",
                    {
                        "length": len(clean_text),
                        "round": round_number + 1
                    }
                )

                return clean_text

            # ----------------------------------------------------
            # Store assistant tool-call message
            # ----------------------------------------------------

            assistant_message = (
                self.normalize_assistant_message(
                    response
                )
            )

            self.messages.append(
                assistant_message
            )

            # ----------------------------------------------------
            # Execute tools
            # ----------------------------------------------------

            if len(tool_calls) > self.MAX_TOOL_CALLS_PER_ROUND:
                self.audit(
                    "tool_call_limit_exceeded",
                    {
                        "requested": len(tool_calls),
                        "allowed": self.MAX_TOOL_CALLS_PER_ROUND,
                        "round": round_number + 1,
                    }
                )

            for (
                call_id,
                tool_name,
                arguments
            ) in tool_calls[
                :self.MAX_TOOL_CALLS_PER_ROUND
            ]:

                print(
                    f"\n🔧 ALIX → {tool_name}"
                )

                result = self.execute_tool(
                    tool_name,
                    arguments
                )

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": self._wrap_untrusted_tool_output(
                            tool_name,
                            result
                        )
                    }
                )

                self._apply_context_boundary()

        warning = (
            "⚠️ وصل ALIX إلى الحد الأقصى "
            "للجولات التنفيذية دون الوصول "
            "إلى نتيجة نهائية."
        )

        self.audit(
            "agent_max_rounds",
            {
                "rounds": self.MAX_ROUNDS
            }
        )

        return warning


__all__ = ["ALIXAgent", "SYSTEM_PROMPT", "TOOLS", "EVIDENCE_PRIORITY_ADDENDUM"]
