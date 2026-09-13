import subprocess
import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

# Import the module under test
import core.executor as executor


class MockPolicy:
    """A minimal Policy implementation for testing."""

    allowed_git_commands = ["status", "log", "diff"]

    def __init__(self, workspace: Path):
        self.workspace = workspace

    # ---------- file path validation ----------
    def validate_file_path(self, path: str):
        try:
            target = (self.workspace / path).resolve()
            # Ensure the target stays inside the workspace
            if self.workspace.resolve() in target.parents or target == self.workspace:
                return target
        except Exception:
            pass
        return None

    # ---------- command handling ----------
    def command_allowed(self, command: str) -> bool:
        # Disallow any command containing the word "disallowed"
        return "disallowed" not in command

    def parse_command(self, command: str):
        # Very simple split; real implementation may be more complex
        return command.split()

    # ---------- search ----------
    def validate_search_pattern(self, pattern: str) -> bool:
        return len(pattern) < 100

    def is_sensitive_path(self, path: Path) -> bool:
        return False


class TestExecutor(unittest.TestCase):
    def setUp(self):
        # Create a temporary workspace directory
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir)
        self.policy = MockPolicy(self.workspace)
        self.exec = executor.SafeExecutor(policy=self.policy)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------- read_file -------------------
    def test_read_file_success(self):
        file_path = self.workspace / "test.txt"
        content = "line1\nline2\nline3"
        file_path.write_text(content, encoding="utf-8")

        result = self.exec.read_file("test.txt", start_line=2, end_line=3)
        self.assertTrue(result["ok"])
        self.assertIn("line2\nline3", result["stdout"])

    def test_read_file_not_allowed(self):
        # Path outside workspace should be rejected
        result = self.exec.read_file("../outside.txt")
        self.assertFalse(result["ok"])
        self.assertIn("المسار غير مسموح", result["message"])

    # ------------------- write_file -------------------
    def test_write_file_creates_backup_and_verifies(self):
        file_path = self.workspace / "data.txt"
        original = "original"
        file_path.write_text(original, encoding="utf-8")

        new_content = "new content"
        result = self.exec.write_file("data.txt", new_content)

        self.assertTrue(result["ok"])
        evidence = result["evidence"]
        self.assertTrue(evidence["backup_created"])
        backup_path = self.workspace / evidence["backup"]
        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.read_text(encoding="utf-8"), original)

    # ------------------- run_command -------------------
    def test_run_command_allowed(self):
        # Use the current Python interpreter to print a known string
        cmd = f"{sys.executable} -c \"print('hello')\""
        result = self.exec.run_command(cmd)

        self.assertTrue(result["ok"])
        self.assertTrue("hello" in str(result.get("stdout", "")) or "hello" in str(result))

    def test_run_command_disallowed(self):
        # Mock policy to reject this specific command
        original_allowed = self.policy.command_allowed

        def reject(command):
            return False

        self.policy.command_allowed = reject
        cmd = f"{sys.executable} -c \"print('no')\""
        result = self.exec.run_command(cmd)

        self.assertFalse(result["ok"])
        self.assertIn("مرفوض", result["message"])

        # Restore original method
        self.policy.command_allowed = original_allowed

    # ------------------- run_python -------------------
    def test_run_python_success(self):
        script_path = self.workspace / "script.py"
        script_path.write_text("print('pyok')", encoding="utf-8")

        result = self.exec.run_python("script.py")
        self.assertTrue(result["ok"])
        self.assertIn("pyok", result["stdout"])

    # ------------------- system_info -------------------
    def test_system_info_collects_allowed_commands(self):
        result = self.exec.system_info()
        self.assertTrue(result["ok"])
        evidence = result["evidence"]
        # At least one of the commands should be present
        self.assertTrue(any(key in evidence for key in ("uname", "memory")))

    # ------------------- git_read_only -------------------
    def test_git_read_only_status_allowed(self):
        # Initialize a git repo in the workspace
        subprocess.run(["git", "init"], cwd=self.workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        result = self.exec.git_read_only(action="status")
        self.assertTrue(result["ok"])
        self.assertIn("git_action", result["evidence"])
        self.assertEqual(result["evidence"]["git_action"], "status")


if __name__ == '__main__':
    unittest.main()