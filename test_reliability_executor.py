import unittest
import subprocess
from unittest import mock

from core.executor import SafeExecutor
from core.policy import Policy


class TestExecutorReliability(unittest.TestCase):

    def setUp(self):
        self.policy = Policy()
        self.executor = SafeExecutor(
            policy=self.policy,
            command_timeout=1,
            python_timeout=1,
        )

    def test_command_timeout_then_recovery(self):
        timeout_result = self.executor.run_command(
            "python3 test_timeout.py"
        )

        self.assertFalse(timeout_result["ok"])
        self.assertTrue(timeout_result["evidence"]["timed_out"])

        recovery_result = self.executor.run_command("echo recovery-ok")

        self.assertTrue(recovery_result["ok"])
        self.assertIn("recovery-ok", recovery_result["stdout"])

    def test_write_permission_error_is_recovered(self):
        with mock.patch(
            "pathlib.Path.write_text",
            side_effect=PermissionError,
        ) as mock_write:
            result = self.executor.write_file(
                "recovery_write.txt",
                "test",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["evidence"], {})
        mock_write.assert_called_once()

        recovery_result = self.executor.write_file(
            "recovery_write.txt",
            "recovered",
        )

        self.assertTrue(recovery_result["ok"])
        self.assertEqual(recovery_result["message"], "تمت كتابة الملف والتحقق منه.")

    def test_delete_permission_error_is_recovered(self):
        target = self.policy.workspace / "recovery_delete.txt"
        target.write_text("delete-me", encoding="utf-8")

        with mock.patch(
            "pathlib.Path.unlink",
            side_effect=PermissionError,
        ) as mock_unlink:
            result = self.executor.delete_file("recovery_delete.txt")

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "delete_file")
        self.assertEqual(result["evidence"], {})
        mock_unlink.assert_called_once()

        recovery_result = self.executor.delete_file(
            "recovery_delete.txt"
        )

        self.assertTrue(recovery_result["ok"])
        self.assertFalse(target.exists())

    def test_write_verification_failure_is_safe(self):
        with mock.patch(
            "pathlib.Path.stat",
            side_effect=OSError("verification failure"),
        ):
            result = self.executor.write_file(
                "verification_failure.txt",
                "test",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "write_file")
        self.assertIn("فشل كتابة الملف", result["message"])

    def test_delete_verification_failure_is_safe(self):
        target = self.policy.workspace / "delete_verification_failure.txt"
        target.write_text("delete-me", encoding="utf-8")

        with mock.patch(
            "pathlib.Path.exists",
            side_effect=[True, True, OSError("verification failure")],
        ):
            result = self.executor.delete_file(
                "delete_verification_failure.txt"
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "delete_file")
        self.assertIn("فشل حذف الملف", result["message"])

    def test_search_failure_is_safe(self):
        with mock.patch(
            "pathlib.Path.rglob",
            side_effect=OSError("search failure"),
        ):
            result = self.executor.search_files(
                "*.py"
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "search_files")
        self.assertIn("فشل البحث", result["message"])

    def test_system_info_partial_failure_is_safe(self):
        class FakeResult:
            def __init__(self, returncode=0, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run(argv, **kwargs):
            if argv[0] == "uname":
                raise OSError("uname failure")
            return FakeResult(
                returncode=0,
                stdout="Mem: 1Gi 2Gi 3Gi",
            )

        with mock.patch(
            "core.executor.subprocess.run",
            side_effect=fake_run,
        ):
            result = self.executor.system_info()

        print("SYSTEM_INFO_PARTIAL_RESULT:", result)

        self.assertEqual(result["action"], "system_info")
        self.assertFalse(result["ok"])
        self.assertIn("uname", result["evidence"])
        self.assertIn("memory", result["evidence"])

    def test_git_failure_then_recovery(self):
        with mock.patch(
            "core.executor.subprocess.run",
            side_effect=OSError("git failure"),
        ):
            result = self.executor.git_read_only("status")

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "git_status")
        self.assertEqual(
            result["evidence"]["git_action"],
            "status",
        )
        self.assertTrue(result["evidence"]["read_only"])
        self.assertFalse(result["evidence"]["verified"])

        recovery_result = self.executor.run_command("echo git-recovery")

        self.assertTrue(recovery_result["ok"])
        self.assertEqual(recovery_result["stdout"].strip(), "git-recovery")

    def test_python_timeout_preserves_partial_output(self):
        timeout_error = TimeoutError("forced timeout")

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=kwargs.get("args") or args[0],
                timeout=kwargs.get("timeout"),
                output="partial-output",
                stderr="partial-error",
            )

        with mock.patch(
            "core.executor.subprocess.run",
            side_effect=fake_run,
        ):
            result = self.executor.run_python("test_timeout.py")

        self.assertFalse(result["ok"])
        self.assertIn("انتهت مهلة", result["message"])
        self.assertIn("partial-output", result["stdout"])
        self.assertIn("partial-error", result["stderr"])

    def test_system_info_total_failure_is_safe(self):
        with mock.patch(
            "core.executor.subprocess.run",
            side_effect=OSError("system info failure"),
        ):
            result = self.executor.system_info()

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "system_info")
        self.assertIn("uname", result["evidence"])
        self.assertIn("memory", result["evidence"])
        self.assertIn("error", result["evidence"]["uname"])
        self.assertIn("error", result["evidence"]["memory"])

    @mock.patch("core.executor.subprocess.run", side_effect=PermissionError)
    def test_subprocess_permission_error_is_recovered(self, mock_run):
        result = self.executor.run_command("echo should-not-start")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "لا توجد صلاحية لتنفيذ هذا الأمر.")
        self.assertTrue(result["evidence"]["verified"])
        mock_run.assert_called_once()


    @mock.patch("core.executor.subprocess.run", side_effect=FileNotFoundError)
    def test_subprocess_file_not_found_is_recovered(self, mock_run):
        result = self.executor.run_command("echo should-not-start")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "الأمر غير موجود في بيئة التنفيذ.")
        self.assertTrue(result["evidence"]["verified"])
        mock_run.assert_called_once()

    def test_missing_command_returns_failure_without_crash(self):
        result = self.executor.run_command("definitely_missing_alix_command")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "الأمر مرفوض بواسطة سياسة الأمان.")
        self.assertTrue(result["evidence"]["verified"])

    def test_python_timeout_then_recovery(self):
        timeout_result = self.executor.run_python("test_timeout.py")
        self.assertFalse(timeout_result["ok"])
        self.assertIn("انتهت مهلة Python", timeout_result["message"])
        recovery_result = self.executor.run_command("echo python-recovery")
        self.assertTrue(recovery_result["ok"])
        self.assertIn("python-recovery", recovery_result["stdout"])

    def test_command_failure_then_recovery(self):
        failed = self.executor.run_command("python3 test_failure.py")
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["returncode"], 7)
        recovery = self.executor.run_command("echo after-failure")
        self.assertTrue(recovery["ok"])
        self.assertIn("after-failure", recovery["stdout"])

if __name__ == "__main__":
    unittest.main()

