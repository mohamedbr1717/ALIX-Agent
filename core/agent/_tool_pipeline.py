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
            # Scheduled mode: the pre-authorized ceiling applies first.
            # Destructive tools are NOT hard-rejected: they escalate to a
            # 180-second Telegram approval window (path ب). A tool NEVER
            # executes without explicit approval.
            permitted = (
                self.policy.scheduled_tool_permitted(
                    name
                )
            )

            if permitted:
                return True

            level = self.policy.tool_permission(name)

            if (
                name in self.policy.SCHEDULER_DENIED_TOOLS
                or level != "destructive"
            ):
                # Hard denylist, or non-destructive over the ceiling:
                # deny outright, no escalation.
                self.audit(
                    "scheduled_tool_denied",
                    {
                        "tool": name,
                        "permission": level,
                        "allowed": getattr(
                            self.policy,
                            "scheduled_allow",
                            "read",
                        ),
                    },
                )
                return False

            return self._scheduled_destructive_approval(
                name, arguments
            )

        if not self.policy.requires_confirmation(name):
            return True

        level = self.policy.tool_permission(name)

        # External confirmer hook (e.g. Telegram Confirmer): if set,
        # delegate the decision instead of console input.
        confirm_fn = getattr(self, "confirm_fn", None)
        if callable(confirm_fn):
            return bool(confirm_fn(name, arguments, level))

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


    def _scheduled_destructive_approval(
        self,
        name: str,
        arguments: dict,
    ) -> bool:
        """Escalation path (ب): suspend a scheduled destructive tool for a
        180-second Telegram approval window.

        Approval → True (the tool executes). Denial or 180s of silence →
        FINAL cancel: the request is archived, the cancellation is written
        to history, the user is notified, and False is returned.
        Fail-closed: any queue error also denies.
        """
        from core import scheduled_approval as sa

        try:
            req = sa.request_approval(
                task_id=getattr(self, "scheduled_task_id", None),
                task_name=getattr(self, "scheduled_task_name", None),
                tool_name=name,
                arguments=arguments,
                level=self.policy.tool_permission(name),
            )
        except Exception:
            self.audit(
                "scheduled_approval_error",
                {"tool": name, "reason": "request_failed"},
            )
            return False

        self.audit(
            "scheduled_approval_requested",
            {"tool": name, "approval_id": req["id"]},
        )

        verdict = sa.await_verdict(req["id"])

        if verdict and verdict.get("approved") is True:
            self.audit(
                "scheduled_approval_granted",
                {"tool": name, "approval_id": req["id"]},
            )
            return True

        reason = (
            "رفض المستخدم الطلب"
            if verdict
            else "انتهت مهلة الموافقة (180 ثانية) دون رد"
        )
        sa.expire_request(req["id"], reason)
        self.audit(
            "scheduled_approval_cancelled",
            {
                "tool": name,
                "approval_id": req["id"],
                "reason": reason,
            },
        )
        # History: the cancellation itself is a user-facing event.
        # (No inverse is computed: nothing executed, nothing to undo.)
        try:
            self._log_history_action(
                name,
                arguments,
                {
                    "ok": False,
                    "cancelled": True,
                    "message": f"المهمة أُلغيت: {reason}",
                },
            )
        except Exception:
            pass
        # Notify the user (the Telegram bot delivers the outbox).
        try:
            sa.notify_user(f"المهمة أُلغيت: {name} — {reason}")
        except Exception:
            pass
        return False


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

            # History logging (fire-and-forget; never breaks execution).
            try:
                self._log_history_action(name, arguments, result)
            except Exception:
                pass

            # Undo: execute the inverse operation directly.
            # The user already confirmed the undo (destructive); the
            # inverse runs without a second confirmation as part of
            # the same approved intent.
            if name == "undo" and result.get("ok"):
                undone = result.get("undone_action")
                if undone and undone.get("inverse"):
                    inverse = undone["inverse"]
                    inv_tool = inverse.get("tool", "")
                    inv_args = inverse.get("arguments", {})
                    if inv_tool and self.policy.tool_allowed(inv_tool):
                        inv_result = self._execute_tool_body(
                            inv_tool, inv_args
                        )
                        # Mark the original action as undone.
                        try:
                            handlers = (
                                self._ensure_migrated_handlers()
                            )
                            mark_fn = handlers.get(
                                "_history_mark_undone"
                            )
                            if mark_fn:
                                mark_fn(undone.get("index", 0))
                        except Exception:
                            pass
                        if inv_result.get("ok"):
                            result["message"] = (
                                f"المهمة أُلغيت: {undone['original'].get('summary', inv_tool)}"
                            )
                        else:
                            result["ok"] = False
                            result["message"] = (
                                f"فشل التراجع: {inv_result.get('error', 'خطأ غير معروف')}"
                            )

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


    def _log_history_action(
        self,
        name: str,
        arguments: dict,
        result: dict,
    ) -> None:
        """Log a tool execution to user-facing history (best-effort).

        Skips the history/undo tools themselves to avoid recursion.
        Uses only the feature_bridge handlers (no direct feature imports).
        """
        if name in ("history", "undo", "_history_log"):
            return
        try:
            handlers = self._ensure_migrated_handlers()
            logger = handlers.get("_history_log")
            inverse_fn = handlers.get("_history_inverse")
            summarize_fn = handlers.get("_history_summarize")
            if logger is None:
                return
            # Redact arguments via policy (never store secrets).
            safe_args = {}
            try:
                allowed = self.policy.tool_arguments(name).get(
                    "allowed", set()
                )
                for key in allowed:
                    if key in arguments:
                        safe_args[key] = arguments[key]
            except Exception:
                safe_args = {}
            inverse = None
            summary = name
            try:
                if inverse_fn:
                    inverse = inverse_fn(name, safe_args, result)
                if summarize_fn:
                    summary = summarize_fn(name, safe_args, result)
            except Exception:
                pass
            logger.execute(
                {
                    "tool_name": name,
                    "arguments": safe_args,
                    "ok": bool(result.get("ok")),
                    "summary": summary,
                    "inverse": inverse,
                }
            )
        except Exception:
            pass

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


