"""SafeExecutor _TerminalMixin (private)."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from core.sandbox import SandboxUnavailable
class _TerminalMixin:
    """Methods moved verbatim."""

    def run_command(self, command: str) -> dict:
        """
        تنفيذ أمر Terminal بشكل مقيد وآمن.

        طبقات الحماية:
        1. Policy allowlist.
        2. تحليل argv بدون shell.
        3. بيئة تنفيذ منقحة من الأسرار.
        4. cwd ثابت داخل workspace.
        5. stdin مغلق.
        6. timeout.
        7. حدود للمخرجات.
        8. نتيجة موحدة مع evidence.
        """

        started = time.monotonic()

        # ---------------------------------------------------------
        # 1. التحقق الأساسي
        # ---------------------------------------------------------
        if not isinstance(command, str):
            return self._base_result(
                "run_command",
                started,
                False,
                "الأمر يجب أن يكون نصًا.",
            ).to_dict()

        command = command.strip()

        if not command:
            return self._base_result(
                "run_command",
                started,
                False,
                "لم يتم تحديد أمر.",
            ).to_dict()

        # ---------------------------------------------------------
        # 2. Policy — نقطة التحكم الأساسية
        # ---------------------------------------------------------
        if not self.policy.command_allowed(command):
            return self._base_result(
                "run_command",
                started,
                False,
                "الأمر مرفوض بواسطة سياسة الأمان.",
                evidence={
                    "policy_allowed": False,
                    "verified": True,
                },
            ).to_dict()

        # ---------------------------------------------------------
        # 3. تحليل الأمر إلى argv
        # ---------------------------------------------------------
        parts = self.policy.parse_command(command)

        if not parts:
            return self._base_result(
                "run_command",
                started,
                False,
                "تعذر تحليل الأمر.",
                evidence={
                    "policy_allowed": True,
                    "parsed": False,
                    "verified": True,
                },
            ).to_dict()

        # ---------------------------------------------------------
        # 4. تحقق إضافي من executable
        # ---------------------------------------------------------
        executable = Path(parts[0]).name

        if not executable:
            return self._base_result(
                "run_command",
                started,
                False,
                "تعذر تحديد البرنامج المطلوب تشغيله.",
            ).to_dict()

        if not self.policy.command_allowed(" ".join(parts)):
            return self._base_result(
                "run_command",
                started,
                False,
                "تم رفض الأمر أثناء التحقق النهائي.",
                evidence={
                    "executable": executable,
                    "verified": True,
                },
            ).to_dict()

        # ---------------------------------------------------------
        # 5. تنفيذ بدون shell
        # ---------------------------------------------------------
        try:
            bounded = self._run_bounded_process(
                parts,
                cwd=self.policy.workspace,
                env=self._safe_environment(),
                timeout=self.command_timeout,
                max_stdout=self.max_output,
                max_stderr=2000,
            )

            ok = (
                bounded["returncode"] == 0
                and not bounded["timed_out"]
            )

            return self._base_result(
                "run_command",
                started,
                ok,
                "تم تنفيذ الأمر."
                if ok
                else (
                    "انتهت مهلة الأمر."
                    if bounded["timed_out"]
                    else "فشل تنفيذ الأمر."
                ),
                stdout=bounded["stdout"],
                stderr=bounded["stderr"],
                returncode=bounded["returncode"],
                evidence={
                    "command": parts,
                    "returncode": bounded["returncode"],
                    "timed_out": bounded["timed_out"],
                    "bounded_output": True,
                    "stdout_bytes": bounded["stdout_bytes"],
                    "stderr_bytes": bounded["stderr_bytes"],
                    "verified": True,
                },
            ).to_dict()


        # ---------------------------------------------------------
        # 8. البرنامج غير موجود
        # ---------------------------------------------------------
        except FileNotFoundError:
            return self._base_result(
                "run_command",
                started,
                False,
                "الأمر غير موجود في بيئة التنفيذ.",
                evidence={
                    "argv": parts,
                    "executable": executable,
                    "verified": True,
                },
            ).to_dict()

        # ---------------------------------------------------------
        # 9. صلاحيات التنفيذ
        # ---------------------------------------------------------
        except PermissionError:
            return self._base_result(
                "run_command",
                started,
                False,
                "لا توجد صلاحية لتنفيذ هذا الأمر.",
                evidence={
                    "argv": parts,
                    "executable": executable,
                    "verified": True,
                },
            ).to_dict()

        # ---------------------------------------------------------
        # 10. أخطاء أخرى
        # ---------------------------------------------------------
        except Exception as exc:
            return self._base_result(
                "run_command",
                started,
                False,
                f"فشل تنفيذ الأمر: {exc}",
                evidence={
                    "argv": parts,
                    "executable": executable,
                    "verified": False,
                },
            ).to_dict()


    def run_python(self, script_path: str) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(script_path)

        if target is None:
            return self._base_result(
                "run_python",
                started,
                False,
                "سكريبت Python غير مسموح أو حساس.",
            ).to_dict()

        if not target.exists() or not target.is_file():
            return self._base_result(
                "run_python",
                started,
                False,
                "سكريبت Python غير موجود.",
            ).to_dict()

        if target.suffix.lower() != ".py":
            return self._base_result(
                "run_python",
                started,
                False,
                "يسمح بتشغيل ملفات .py فقط.",
            ).to_dict()

        # SECURITY FIX: this used to run
        # subprocess.run([sys.executable, script]) directly -- a full,
        # unsandboxed interpreter with no filesystem or network
        # isolation. It now goes through core/sandbox.py's
        # ProotSandbox, which provides real, kernel/ptrace-enforced
        # filesystem isolation and resource limits. If a real sandbox
        # can't be constructed (e.g. `proot` isn't installed), this
        # fails closed instead of silently falling back to
        # unsandboxed execution.

        try:
            sandbox = self._sandbox_cls(workspace=self.policy.workspace)
        except SandboxUnavailable as exc:
            return self._base_result(
                "run_python",
                started,
                False,
                f"تم رفض التنفيذ: العزل الحقيقي غير متاح ({exc})",
            ).to_dict()

        result = sandbox.run(
            script_path=target,
            timeout=self.python_timeout,
            env=self._safe_environment(),
        )

        ok = bool(result.get("ok"))

        return self._base_result(
            "run_python",
            started,
            ok,
            "تم تشغيل Python بنجاح داخل العزل."
            if ok
            else result.get("error", "فشل التنفيذ داخل العزل."),
            stdout=self._truncate(result.get("stdout", ""), self.max_output),
            stderr=self._truncate(result.get("stderr", ""), 2000),
            returncode=result.get("return_code"),
            evidence={
                "script": str(
                    target.relative_to(
                        self.policy.workspace
                    )
                ),
                "sandboxed": True,
                "isolation": "proot",
                "timed_out": result.get("timed_out", False),
            },
        ).to_dict()


    def system_info(self) -> dict:

        started = time.monotonic()

        results = {}

        for argv, key in (
            (["uname", "-a"], "uname"),
            (["free", "-h"], "memory"),
        ):
            if not self.policy.command_allowed(" ".join(argv)):
                continue

            try:
                result = subprocess.run(
                    argv,
                    cwd=self.policy.workspace,
                    env=self._safe_environment(),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=False,
                )

                results[key] = {
                    "returncode": result.returncode,
                    "stdout": self._truncate(
                        result.stdout,
                        1500,
                    ),
                    "stderr": self._truncate(
                        result.stderr,
                        1000,
                    ),
                }

            except Exception as exc:
                results[key] = {
                    "error": str(exc)
                }

        all_success = (
            len(results) == 2
            and all("error" not in item for item in results.values())
            and all(item.get("returncode") == 0 for item in results.values())
        )

        return self._base_result(
            "system_info",
            started,
            all_success,
            "تم جمع معلومات النظام."
            if all_success
            else "فشل جزئي في جمع معلومات النظام.",
            evidence=results,
        ).to_dict()


    def git_read_only(
        self,
        action: str = "status",
    ) -> dict:

        started = time.monotonic()

        if action not in self.policy.allowed_git_commands:
            return self._base_result(
                "git_status",
                started,
                False,
                "عملية Git غير مسموحة.",
            ).to_dict()

        command = ["git", action]

        if not self.policy.command_allowed(
            " ".join(command)
        ):
            return self._base_result(
                "git_status",
                started,
                False,
                "عملية Git مرفوضة بواسطة Policy.",
            ).to_dict()

        try:
            bounded = self._run_bounded_process(
                command,
                cwd=self.policy.workspace,
                env=self._safe_environment(),
                timeout=self.command_timeout,
                max_stdout=self.max_output,
                max_stderr=2000,
            )

            ok = (
                bounded["returncode"] == 0
                and not bounded["timed_out"]
            )

            return self._base_result(
                "git_status",
                started,
                ok,
                "تم تنفيذ Git."
                if ok
                else (
                    "انتهت مهلة Git."
                    if bounded["timed_out"]
                    else "فشلت عملية Git."
                ),
                stdout=bounded["stdout"],
                stderr=bounded["stderr"],
                returncode=bounded["returncode"],
                evidence={
                    "git_action": action,
                    "read_only": True,
                    "returncode": bounded["returncode"],
                    "timed_out": bounded["timed_out"],
                    "bounded_output": True,
                    "stdout_bytes": bounded["stdout_bytes"],
                    "stderr_bytes": bounded["stderr_bytes"],
                    "verified": True,
                },
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "git_status",
                started,
                False,
                f"فشل Git: {exc}",
                evidence={
                    "git_action": action,
                    "read_only": True,
                    "verified": False,
                },
            ).to_dict()


