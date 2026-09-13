from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from core.policy import Policy


class ExecutionResult:
    """نتيجة موحدة لأي عملية تنفيذ."""

    def __init__(
        self,
        ok: bool,
        action: str,
        message: str = "",
        stdout: str = "",
        stderr: str = "",
        returncode: Optional[int] = None,
        evidence: Optional[dict] = None,
        duration: float = 0.0,
    ):
        self.ok = bool(ok)
        self.action = action
        self.message = message
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.evidence = evidence or {}
        self.duration = round(duration, 3)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "action": self.action,
            "message": self.message,
            "stdout": self.stdout[:4000],
            "stderr": self.stderr[:2000],
            "returncode": self.returncode,
            "evidence": self.evidence,
            "duration": self.duration,
        }


class SafeExecutor:
    """
    محرك التنفيذ الآمن لـ ALIX.

    المبدأ:
        Agent
          ↓
        Policy
          ↓
        SafeExecutor
          ↓
        subprocess

    لا يقوم هذا الكلاس بمنح صلاحيات جديدة.
    بل يطبق القيود التي تحددها Policy.
    """

    def __init__(
        self,
        policy: Optional[Policy] = None,
        command_timeout: int = 30,
        python_timeout: int = 30,
        max_output: int = 4000,
    ):
        self.policy = policy or Policy()

        self.command_timeout = max(1, int(command_timeout))
        self.python_timeout = max(1, int(python_timeout))
        self.max_output = max(500, int(max_output))

    # ============================================================
    # Internal helpers
    # ============================================================

    @staticmethod
    def _truncate(value: Any, limit: int) -> str:
        if value is None:
            return ""

        text = str(value)

        if len(text) <= limit:
            return text

        marker = "\n...[تم اقتطاع المخرجات]..."

        if limit <= len(marker):
            return marker[:limit]

        return text[:limit - len(marker)] + marker

    def _run_bounded_process(
        self,
        argv,
        *,
        cwd,
        env,
        timeout,
        max_stdout=None,
        max_stderr=None,
    ):
        """Run a child process with continuously drained bounded output."""

        import os
        import signal
        import threading
        from collections import deque

        stdout_limit = (
            self.max_output
            if max_stdout is None
            else max(1, int(max_stdout))
        )

        stderr_limit = (
            2000
            if max_stderr is None
            else max(1, int(max_stderr))
        )

        stdout_chunks = deque()
        stderr_chunks = deque()

        stdout_bytes = 0
        stderr_bytes = 0

        lock = threading.Lock()

        def drain(stream, chunks, limit, stream_name):
            nonlocal stdout_bytes, stderr_bytes

            try:
                while True:
                    data = stream.read(65536)

                    if not data:
                        break

                    if isinstance(data, str):
                        data = data.encode(
                            "utf-8",
                            "replace",
                        )

                    with lock:
                        if stream_name == "stdout":
                            stdout_bytes += len(data)
                        else:
                            stderr_bytes += len(data)

                        kept = sum(len(x) for x in chunks)
                        remaining = limit - kept

                        if remaining > 0:
                            chunks.append(
                                data[:remaining]
                            )

            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        proc = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=(
                os.name == "posix"
            ),
        )

        stdout_thread = threading.Thread(
            target=drain,
            args=(
                proc.stdout,
                stdout_chunks,
                stdout_limit,
                "stdout",
            ),
            daemon=True,
        )

        stderr_thread = threading.Thread(
            target=drain,
            args=(
                proc.stderr,
                stderr_chunks,
                stderr_limit,
                "stderr",
            ),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        timed_out = False

        try:
            proc.wait(
                timeout=max(
                    1,
                    int(timeout),
                )
            )

        except subprocess.TimeoutExpired:
            timed_out = True

            try:
                if os.name == "posix":
                    os.killpg(
                        proc.pid,
                        signal.SIGKILL,
                    )
                else:
                    proc.kill()

            except ProcessLookupError:
                pass

            proc.wait()

        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        stdout = b"".join(
            stdout_chunks
        ).decode(
            "utf-8",
            "replace",
        )

        stderr = b"".join(
            stderr_chunks
        ).decode(
            "utf-8",
            "replace",
        )

        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "stdout_truncated": (
                stdout_bytes > stdout_limit
            ),
            "stderr_truncated": (
                stderr_bytes > stderr_limit
            ),
            "timed_out": timed_out,
        }

    def _safe_environment(self) -> dict:
        """
        بيئة تنفيذ محدودة.

        لا نقوم هنا بحذف PATH أو HOME لأن Python وTermux
        يحتاجان إلى بيئة أساسية للعمل، لكننا نمنع تمرير
        متغيرات سرية معروفة إلى العمليات التي ينشئها ALIX.
        """

        env = dict(os.environ)

        sensitive_prefixes = (
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "AWS_ACCESS_KEY",
            "AWS_SECRET",
            "GITHUB_TOKEN",
            "GH_TOKEN",
        )

        for key in list(env.keys()):
            upper = key.upper()

            if any(
                upper == prefix or upper.startswith(prefix + "_")
                for prefix in sensitive_prefixes
            ):
                env.pop(key, None)

        return env

    def _base_result(
        self,
        action: str,
        started: float,
        ok: bool,
        message: str = "",
        **kwargs,
    ) -> ExecutionResult:
        return ExecutionResult(
            ok=ok,
            action=action,
            message=message,
            duration=time.monotonic() - started,
            **kwargs,
        )

    # ============================================================
    # File operations
    # ============================================================

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "read_file",
                started,
                False,
                "المسار غير مسموح أو يشير إلى ملف حساس.",
            ).to_dict()

        if not target.exists():
            return self._base_result(
                "read_file",
                started,
                False,
                "الملف غير موجود.",
            ).to_dict()

        if not target.is_file():
            return self._base_result(
                "read_file",
                started,
                False,
                "المسار ليس ملفًا.",
            ).to_dict()

        try:
            lines = target.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()

            start = max(1, int(start_line))

            if end_line is None:
                end = len(lines)
            else:
                end = max(start, int(end_line))

            selected = lines[start - 1:end]

            content = "\n".join(selected)

            evidence = {
                "path": str(target.relative_to(self.policy.workspace)),
                "exists": True,
                "is_file": True,
                "line_count": len(lines),
                "returned_lines": len(selected),
                "size_bytes": target.stat().st_size,
            }

            return self._base_result(
                "read_file",
                started,
                True,
                "تمت قراءة الملف.",
                stdout=self._truncate(content, self.max_output),
                evidence=evidence,
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "read_file",
                started,
                False,
                f"فشل قراءة الملف: {exc}",
            ).to_dict()

    def write_file(
        self,
        path: str,
        content: str,
    ) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "write_file",
                started,
                False,
                "المسار غير مسموح أو يشير إلى ملف حساس.",
            ).to_dict()

        if not isinstance(content, str):
            return self._base_result(
                "write_file",
                started,
                False,
                "محتوى الملف يجب أن يكون نصًا.",
            ).to_dict()

        try:
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            # حفظ نسخة احتياطية قبل الكتابة إذا كان الملف موجودًا.
            backup_path = None

            if target.exists() and target.is_file():
                backup_path = target.with_name(
                    target.name + ".alix-backup"
                )

                backup_path.write_bytes(
                    target.read_bytes()
                )

            target.write_text(
                content,
                encoding="utf-8",
            )

            # تحقق مستقل بعد الكتابة.
            exists = target.exists()
            is_file = target.is_file()

            size = target.stat().st_size if is_file else 0

            verified = (
                exists
                and is_file
                and size == len(content.encode("utf-8"))
            )

            evidence = {
                "path": str(target.relative_to(self.policy.workspace)),
                "exists_after_write": exists,
                "is_file_after_write": is_file,
                "size_bytes": size,
                "verified": verified,
                "backup_created": bool(backup_path),
            }

            if backup_path:
                evidence["backup"] = str(
                    backup_path.relative_to(self.policy.workspace)
                )

            return self._base_result(
                "write_file",
                started,
                verified,
                "تمت كتابة الملف والتحقق منه."
                if verified
                else "تمت محاولة الكتابة ولكن فشل التحقق.",
                evidence=evidence,
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "write_file",
                started,
                False,
                f"فشل كتابة الملف: {exc}",
            ).to_dict()

    def create_directory(self, path: str) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "create_directory",
                started,
                False,
                "المسار غير مسموح.",
            ).to_dict()

        try:
            target.mkdir(
                parents=True,
                exist_ok=True,
            )

            verified = target.exists() and target.is_dir()

            return self._base_result(
                "create_directory",
                started,
                verified,
                "تم إنشاء المجلد والتحقق منه."
                if verified
                else "فشل التحقق من إنشاء المجلد.",
                evidence={
                    "path": str(
                        target.relative_to(self.policy.workspace)
                    ),
                    "exists": target.exists(),
                    "is_directory": target.is_dir(),
                    "verified": verified,
                },
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "create_directory",
                started,
                False,
                f"فشل إنشاء المجلد: {exc}",
            ).to_dict()

    def delete_file(self, path: str) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "delete_file",
                started,
                False,
                "المسار غير مسموح أو حساس.",
            ).to_dict()

        if not target.exists():
            return self._base_result(
                "delete_file",
                started,
                False,
                "الملف غير موجود.",
            ).to_dict()

        if not target.is_file():
            return self._base_result(
                "delete_file",
                started,
                False,
                "الحذف مسموح للملفات فقط.",
            ).to_dict()

        try:
            backup_path = target.with_name(
                target.name + ".alix-delete-backup"
            )

            backup_path.write_bytes(
                target.read_bytes()
            )

            target.unlink()

            verified = not target.exists()

            return self._base_result(
                "delete_file",
                started,
                verified,
                "تم حذف الملف والتحقق من الحذف."
                if verified
                else "فشل التحقق من الحذف.",
                evidence={
                    "path": str(
                        target.relative_to(self.policy.workspace)
                    ),
                    "deleted": verified,
                    "backup": str(
                        backup_path.relative_to(self.policy.workspace)
                    ),
                    "rollback_available": backup_path.exists(),
                },
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "delete_file",
                started,
                False,
                f"فشل حذف الملف: {exc}",
            ).to_dict()

    # ============================================================
    # Search
    # ============================================================

    def search_files(
        self,
        pattern: str,
        path: str = ".",
        max_matches: int = 20,
    ) -> dict:

        started = time.monotonic()

        if not self.policy.validate_search_pattern(pattern):
            return self._base_result(
                "search_files",
                started,
                False,
                "نمط البحث غير صالح أو طويل جدًا.",
            ).to_dict()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "search_files",
                started,
                False,
                "مسار البحث غير مسموح.",
            ).to_dict()

        if not target.exists():
            return self._base_result(
                "search_files",
                started,
                False,
                "مسار البحث غير موجود.",
            ).to_dict()

        matches = []

        try:
            files = (
                [target]
                if target.is_file()
                else target.rglob("*")
            )

            for file_path in files:

                if len(matches) >= max_matches:
                    break

                if not file_path.is_file():
                    continue

                if self.policy.is_sensitive_path(file_path):
                    continue

                try:
                    text = file_path.read_text(
                        encoding="utf-8",
                        errors="ignore",
                    )
                except Exception:
                    continue

                for line_number, line in enumerate(
                    text.splitlines(),
                    1,
                ):
                    if pattern.lower() in line.lower():

                        relative = str(
                            file_path.relative_to(
                                self.policy.workspace
                            )
                        )

                        matches.append(
                            {
                                "file": relative,
                                "line": line_number,
                                "content": self._truncate(
                                    line.strip(),
                                    500,
                                ),
                            }
                        )

                        if len(matches) >= max_matches:
                            break

            return self._base_result(
                "search_files",
                started,
                True,
                "اكتمل البحث.",
                evidence={
                    "pattern": pattern,
                    "matches": matches,
                    "count": len(matches),
                    "truncated": len(matches) >= max_matches,
                },
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "search_files",
                started,
                False,
                f"فشل البحث: {exc}",
            ).to_dict()

    # ============================================================
    # Terminal
    # ============================================================

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

            stdout = self._truncate(
                result.stdout,
                self.max_output,
            )

            stderr = self._truncate(
                result.stderr,
                2000,
            )

            ok = result.returncode == 0

            # -----------------------------------------------------
            # 6. Evidence
            # -----------------------------------------------------
            evidence = {
                "argv": parts,
                "executable": executable,
                "cwd": str(self.policy.workspace),
                "returncode": result.returncode,
                "stdout_present": bool(stdout),
                "stderr_present": bool(stderr),
                "verified": True,
            }

            return self._base_result(
                "run_command",
                started,
                ok,
                (
                    "تم تنفيذ الأمر والتحقق من نجاحه."
                    if ok
                    else "تم تنفيذ الأمر لكنه انتهى برمز خطأ."
                ),
                stdout=stdout,
                stderr=stderr,
                returncode=result.returncode,
                evidence=evidence,
            ).to_dict()

        # ---------------------------------------------------------
        # 7. Timeout
        # ---------------------------------------------------------
        except subprocess.TimeoutExpired as exc:
            stdout = self._truncate(
                getattr(exc, "stdout", ""),
                self.max_output,
            )

            stderr = self._truncate(
                getattr(exc, "stderr", ""),
                2000,
            )

            return self._base_result(
                "run_command",
                started,
                False,
                f"انتهت مهلة التنفيذ ({self.command_timeout} ثانية).",
                stdout=stdout,
                stderr=stderr,
                evidence={
                    "argv": parts,
                    "executable": executable,
                    "timeout": self.command_timeout,
                    "timed_out": True,
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

    # ============================================================
    # Python
    # ============================================================
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

        command = [
            sys.executable,
            str(target),
        ]

        try:
            bounded = self._run_bounded_process(
                command,
                cwd=self.policy.workspace,
                env=self._safe_environment(),
                timeout=self.python_timeout,
                max_stdout=self.max_output,
                max_stderr=2000,
            )

            ok = (
                bounded["returncode"] == 0
                and not bounded["timed_out"]
            )

            return self._base_result(
                "run_python",
                started,
                ok,
                "تم تشغيل Python بنجاح."
                if ok
                else (
                    f"انتهت مهلة Python ({self.python_timeout} ثانية)."
                    if bounded["timed_out"]
                    else "انتهى Python بخطأ."
                ),
                stdout=bounded["stdout"],
                stderr=bounded["stderr"],
                returncode=bounded["returncode"],
                evidence={
                    "script": str(
                        target.relative_to(
                            self.policy.workspace
                        )
                    ),
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
                "run_python",
                started,
                False,
                f"فشل تشغيل Python: {exc}",
                evidence={
                    "script": str(
                        target.relative_to(
                            self.policy.workspace
                        )
                    ),
                    "verified": False,
                },
            ).to_dict()


    # ============================================================
    # System information
    # ============================================================

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

    # ============================================================
    # Git
    # ============================================================

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

    # ============================================================
    # Verification
    # ============================================================

    def verify_file(
        self,
        path: str,
    ) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "verify_file",
                started,
                False,
                "المسار غير مسموح.",
            ).to_dict()

        exists = target.exists()
        is_file = target.is_file() if exists else False

        evidence = {
            "path": str(
                target.relative_to(
                    self.policy.workspace
                )
            ),
            "exists": exists,
            "is_file": is_file,
            "size_bytes": (
                target.stat().st_size
                if is_file
                else 0
            ),
            "verified": exists and is_file,
        }

        return self._base_result(
            "verify_file",
            started,
            exists and is_file,
            "تم التحقق من الملف."
            if exists and is_file
            else "الملف غير موجود.",
            evidence=evidence,
        ).to_dict()
