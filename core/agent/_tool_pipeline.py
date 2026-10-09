"""ALIXAgent _ToolPipelineMixin (private)."""
from __future__ import annotations

import json
import time

from core.prompt_guard import guard_tool_output
from core.feature_bridge import build_migrated_tool_handlers
class _ToolPipelineMixin:
    """Methods moved verbatim."""

    def confirm_tool(
        self,
        name: str,
        arguments: dict
    ) -> bool:
        """
        يطلب موافقة المستخدم على العمليات الحساسة.
        """

        if getattr(
            self.policy, "scheduled_mode", False
        ):
            # لا يوجد مستخدم للتأكيد في المهام المجدولة:
            # القرار هو السقف المصرَّح به مسبقًا عند الجدولة.
            permitted = (
                self.policy.scheduled_tool_permitted(
                    name
                )
            )

            if not permitted:
                self.audit(
                    "scheduled_tool_denied",
                    {
                        "tool": name,
                        "permission": (
                            self.policy.tool_permission(
                                name
                            )
                        ),
                        "allowed": getattr(
                            self.policy,
                            "scheduled_allow",
                            "read",
                        ),
                    },
                )

            return permitted

        if not self.policy.requires_confirmation(name):
            return True

        level = self.policy.tool_permission(name)

        print()
        print("⚠️ ALIX يطلب موافقة للتنفيذ")
        print(f"الأداة: {self._safe_display(name)}")
        print(f"المستوى: {self._safe_display(level)}")
        print(
            "المعاملات:",
            self._safe_display(arguments)
        )

        if level == "destructive":
            print(
                "🚨 تحذير: هذه عملية تدميرية."
            )

        try:
            answer = input(
                "هل تسمح؟ [y/N]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.audit(
                "permission_input_failure",
                {
                    "tool": name,
                    "permission": level,
                    "reason": "input_unavailable"
                }
            )
            return False

        approved = answer in {
            "y",
            "yes",
            "نعم"
        }

        self.audit(
            "permission_decision",
            {
                "tool": name,
                "permission": level,
                "approved": approved
            }
        )

        return approved


    def _wrap_untrusted_tool_output(
        self,
        tool_name: str,
        result: dict
    ) -> str:
        # Prompt-injection defense: scan + redact + delimit + log.
        payload = json.dumps(
            result,
            ensure_ascii=False
        )

        block, findings = guard_tool_output(tool_name, payload)

        if findings:
            try:
                self.observability.emit(
                    "prompt_guard.detection",
                    {
                        "tool": tool_name,
                        "count": len(findings),
                        "worst_severity": max(
                            findings,
                            key=lambda f: {"low": 0, "medium": 1, "high": 2}[f.severity],
                        ).severity,
                        "patterns": sorted({f.pattern for f in findings}),
                    },
                )
            except Exception:
                pass  # guard must never break the agent loop

        return block


    def execute_tool(
        self,
        name: str,
        arguments: dict
    ) -> dict:

        if not isinstance(arguments, dict):
            result = {
                "ok": False,
                "error": "معاملات الأداة يجب أن تكون كائنًا من نوع dict.",
            }

            self.audit(
                "tool_arguments_denied",
                {
                    "tool": str(name),
                    "reason": "arguments_not_dict",
                }
            )

            return result

        if not self.policy.tool_allowed(name):
            message = f"الأداة غير مسموحة: {name}"

            result = {
                "ok": False,
                "action": str(name),
                "message": message,
                "error": message,
            }

            self.audit(
                "tool_denied",
                {"tool": name}
            )

            return result

        # Capability gate: disabled capabilities fail closed
        # before argument validation, confirmation, or execution.
        if not self.policy.capability_allowed(name):
            result = {
                "ok": False,
                "action": str(name),
                "error": f"الأداة معطلة أمنيًا: {name}",
            }

            self.audit(
                "tool_capability_denied",
                {
                    "tool": name,
                    "permission": self.policy.tool_permission(name),
                }
            )

            return result

        # Generic argument validation must happen before
        # confirmation and before any tool execution.
        try:
            arguments_valid = self.policy.validate_tool_arguments(
                name,
                arguments,
            )
        except AttributeError:
            # Compatibility fallback for older Policy implementations.
            arguments_valid = self.policy.validate_command_arguments(
                arguments
            )

        if not arguments_valid:
            result = {
                "ok": False,
                "error": "معطيات الأداة غير صالحة أو مرفوضة بواسطة Policy.",
            }

            self.audit(
                "tool_arguments_denied",
                {
                    "tool": name,
                }
            )

            return result

        if not self.confirm_tool(
            name,
            arguments
        ):
            result = {
                "ok": False,
                "error": "رفض المستخدم تنفيذ العملية."
            }

            self.audit(
                "tool_confirmation_denied",
                {
                    "tool": name,
                    "permission": self.policy.tool_permission(
                        name
                    )
                }
            )

            return result

        execution_id = self.observability.new_id()
        tool_started = time.monotonic()

        self.audit(
            "tool_start",
            {
                "tool": name,
                "permission": self.policy.tool_permission(
                    name
                )
            },
            execution_id=execution_id,
            status="started",
        )

        result = None
        final_status = "failure"

        try:
            result = self._execute_tool_body(
                name,
                arguments,
            )

            if not isinstance(result, dict):
                result = {
                    "ok": False,
                    "error": "نتيجة الأداة غير صالحة."
                }

            evidence = result.get("evidence", {})

            if (
                isinstance(evidence, dict)
                and evidence.get("timed_out") is True
            ):
                final_status = "timeout"
            elif result.get("ok") is True:
                final_status = "success"
            else:
                final_status = "failure"

            return result

        except Exception as exc:

            final_status = "exception"

            self.audit(
                "tool_exception",
                {
                    "tool": name,
                    "error": str(exc)
                },
                execution_id=execution_id,
                status="exception",
                latency_ms=(
                    time.monotonic() - tool_started
                ) * 1000.0,
            )

            result = {
                "ok": False,
                "error": (
                    f"حدث خطأ أثناء تنفيذ الأداة: {exc}"
                )
            }

            return result

        finally:
            self.audit(
                "tool_finished",
                {"tool": name},
                execution_id=execution_id,
                status=final_status,
                latency_ms=(
                    time.monotonic() - tool_started
                ) * 1000.0,
            )


    def _ensure_migrated_handlers(self):
        """تهيئة handlers المُهاجرة مرة واحدة عند الحاجة.

        المسار الطبيعي يبنيها في __init__، بينما بعض مسارات
        الاختبار/الاستدعاء المباشر قد تنشئ الكائن عبر __new__.
        لا نعيد البناء بعد أول تهيئة.
        """
        if not hasattr(self, "_migrated_handlers"):
            self._migrated_handlers = build_migrated_tool_handlers(
                self.policy, getattr(self, "memory", None)
            )

        return self._migrated_handlers


    def _execute_tool_body(
        self,
        name: str,
        arguments: dict,
    ) -> dict:

        migrated_handlers = self._ensure_migrated_handlers()

        if name in migrated_handlers:
            return migrated_handlers[name](**arguments)






        return {
            "ok": False,
            "error": f"أداة غير معالجة: {name}"
        }


