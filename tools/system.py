import os
import platform
import shutil
import subprocess


class SystemTools:
    """
    أدوات النظام الخاصة بـ ALIX.

    لا يوجد تنفيذ Shell مفتوح.
    أوامر shell تمر أولاً عبر Policy.
    """

    def __init__(self, policy=None):
        self.policy = policy

    # ========================================================
    # SYSTEM INFO
    # ========================================================

    def system_info(self):

        try:
            disk = shutil.disk_usage("/")

            return {
                "ok": True,
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
                "home": str(
                    os.path.expanduser("~")
                ),
                "disk_total": disk.total,
                "disk_used": disk.used,
                "disk_free": disk.free,
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    # ========================================================
    # RUN COMMAND
    # ========================================================

    def run_command(
        self,
        command,
        timeout=30
    ):

        if self.policy is None:

            return {
                "ok": False,
                "error": (
                    "Policy غير متوفرة."
                )
            }

        if not isinstance(
            command,
            str
        ):

            return {
                "ok": False,
                "error": (
                    "command يجب أن يكون نصًا."
                )
            }

        command = command.strip()

        if not command:

            return {
                "ok": False,
                "error": "الأمر فارغ."
            }

        # ----------------------------------------------------
        # Security check
        # ----------------------------------------------------

        if not self.policy.command_allowed(
            command
        ):

            return {
                "ok": False,
                "error": (
                    "تم رفض الأمر بواسطة "
                    "سياسة الأمان."
                )
            }

        # ----------------------------------------------------
        # Timeout
        # ----------------------------------------------------

        try:

            timeout = int(timeout)

        except Exception:

            timeout = 30

        timeout = max(
            1,
            min(timeout, 60)
        )

        # ----------------------------------------------------
        # Execute
        # ----------------------------------------------------

        try:

            result = subprocess.run(
                command,
                shell=True,
                cwd=str(
                    self.policy.workspace
                ),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return {
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:]
            }

        except subprocess.TimeoutExpired:

            return {
                "ok": False,
                "error": (
                    f"انتهت المهلة بعد "
                    f"{timeout} ثانية."
                )
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    # ========================================================
    # GIT STATUS
    # ========================================================

    def git_status(self, path="."):

        if self.policy is None:

            return {
                "ok": False,
                "error": (
                    "Policy غير متوفرة."
                )
            }

        target = self.policy.resolve_path(
            path
        )

        if target is None:

            return {
                "ok": False,
                "error": (
                    "المسار خارج مساحة ALIX."
                )
            }

        if not target.exists():

            return {
                "ok": False,
                "error": (
                    "المسار غير موجود."
                )
            }

        try:

            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(target),
                    "status",
                    "--short",
                    "--branch"
                ],
                cwd=str(
                    self.policy.workspace
                ),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=15
            )

            return {
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-4000:]
            }

        except subprocess.TimeoutExpired:

            return {
                "ok": False,
                "error": (
                    "انتهت مهلة Git."
                )
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }
