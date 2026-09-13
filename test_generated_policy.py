import unittest
import tempfile
import shutil
from pathlib import Path

import core.policy as policy


class TestPolicy(unittest.TestCase):
    def setUp(self):
        # Create a temporary workspace and patch the Policy instance to use it.
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.policy = policy.Policy()
        self.policy.base_dir = self.tmp_dir
        self.policy.workspace = (self.tmp_dir / "workspace").resolve()
        self.policy.workspace.mkdir(parents=True, exist_ok=True)

        # Create a non‑sensitive file and a sensitive file.
        (self.policy.workspace / "normal.txt").write_text("hello")
        (self.policy.workspace / ".env").write_text("SECRET=1")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    # ---------- Path handling ----------
    def test_resolve_path_relative(self):
        p = self.policy.resolve_path("normal.txt")
        self.assertIsNotNone(p)
        self.assertTrue(p.is_file())
        self.assertEqual(p.name, "normal.txt")

    def test_resolve_path_absolute_outside_workspace(self):
        # Absolute system path should be rejected.
        p = self.policy.resolve_path("/etc/passwd")
        self.assertIsNone(p)

    def test_resolve_path_traversal_blocked(self):
        p = self.policy.resolve_path("../outside.txt")
        self.assertIsNone(p)

    def test_is_sensitive_path_detection(self):
        sensitive = self.policy.workspace / ".env"
        self.assertTrue(self.policy.is_sensitive_path(sensitive))
        normal = self.policy.workspace / "normal.txt"
        self.assertFalse(self.policy.is_sensitive_path(normal))

    # ---------- Command parsing ----------
    def test_parse_command_valid(self):
        parts = self.policy.parse_command("ls -l /tmp")
        self.assertEqual(parts, ["ls", "-l", "/tmp"])

    def test_parse_command_blocked_pattern(self):
        # Contains a blocked operator ';'
        self.assertIsNone(self.policy.parse_command("ls; rm -rf ."))

    # ---------- Command allowance ----------
    def test_command_allowed_simple(self):
        self.assertTrue(self.policy.command_allowed("ls"))
        self.assertFalse(self.policy.command_allowed("rm -rf ."))

    def test_command_allowed_sensitive_file(self):
        # cat on a sensitive file should be rejected
        cmd = f"cat {self.policy.workspace / '.env'}"
        self.assertFalse(self.policy.command_allowed(cmd))

    def test_command_allowed_python_restrictions(self):
        # Allowed python script inside workspace
        script = self.policy.workspace / "script.py"
        script.write_text("print('ok')")
        cmd = f"python {script.relative_to(self.policy.workspace)}"
        self.assertTrue(self.policy.command_allowed(cmd))

        # Disallowed inline execution
        self.assertFalse(self.policy.command_allowed("python -c 'print(1)'"))

    def test_command_allowed_git(self):
        self.assertTrue(self.policy.command_allowed("git status"))
        # push is not in allowed_git_commands
        self.assertFalse(self.policy.command_allowed("git push"))

    # ---------- Tool permissions ----------
    def test_tool_allowed_and_permission(self):
        self.assertTrue(self.policy.tool_allowed("read_file"))
        self.assertEqual(self.policy.tool_permission("read_file"), "read")
        self.assertFalse(self.policy.tool_allowed("nonexistent_tool"))

    def test_requires_confirmation(self):
        self.assertTrue(self.policy.requires_confirmation("write_file"))
        self.assertFalse(self.policy.requires_confirmation("read_file"))

    # ---------- Tool argument validation ----------
    def test_validate_tool_arguments_read_file(self):
        args = {"path": "normal.txt"}
        self.assertTrue(self.policy.validate_tool_arguments("read_file", args))

        # Sensitive path should be rejected
        args = {"path": ".env"}
        self.assertFalse(self.policy.validate_tool_arguments("read_file", args))

    def test_validate_tool_arguments_run_command(self):
        args = {"command": "ls -a"}
        self.assertTrue(self.policy.validate_tool_arguments("run_command", args))

        args = {"command": "rm -rf ."}
        self.assertFalse(self.policy.validate_tool_arguments("run_command", args))

    def test_validate_tool_arguments_run_python(self):
        # Valid script
        script = self.policy.workspace / "good.py"
        script.write_text("print('ok')")
        args = {"script_path": "good.py"}
        self.assertTrue(self.policy.validate_tool_arguments("run_python", args))

        # Disallowed absolute path
        args = {"script_path": "/etc/passwd"}
        self.assertFalse(self.policy.validate_tool_arguments("run_python", args))

        # Disallowed extension
        script_txt = self.policy.workspace / "bad.txt"
        script_txt.write_text("data")
        args = {"script_path": "bad.txt"}
        self.assertFalse(self.policy.validate_tool_arguments("run_python", args))

    def test_validate_tool_arguments_search_files(self):
        args = {"path": ".", "pattern": "hello", "max_matches": 5}
        self.assertTrue(self.policy.validate_tool_arguments("search_files", args))

        # Exceed max matches
        args["max_matches"] = 100
        self.assertFalse(self.policy.validate_tool_arguments("search_files", args))

    # ---------- Generic argument validation ----------
    def test_validate_command_arguments(self):
        good = {"cmd": "ls", "opt": "a" * 100}
        self.assertTrue(self.policy.validate_command_arguments(good))

        bad = {"cmd": "x" * 2_000_001}
        self.assertFalse(self.policy.validate_command_arguments(bad))


if __name__ == '__main__':
    unittest.main()