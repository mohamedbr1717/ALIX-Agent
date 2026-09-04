import unittest
from pathlib import Path
from unittest.mock import patch

from core.policy import Policy


class TestPolicyCoverageV8(unittest.TestCase):

    def setUp(self):
        self.policy = Policy()
        self.workspace = self.policy.workspace
        self.test_file = self.workspace / "coverage_test.py"
        self.normal_file = self.workspace / "normal.txt"

    # ---------------------------------------------------------
    # Basic tool permissions
    # ---------------------------------------------------------

    def test_tool_permissions(self):
        self.assertTrue(self.policy.tool_allowed("read_file"))
        self.assertTrue(self.policy.tool_allowed("write_file"))
        self.assertTrue(self.policy.tool_allowed("run_command"))
        self.assertTrue(self.policy.tool_allowed("delete_file"))

        self.assertFalse(self.policy.tool_allowed("unknown_tool"))
        self.assertFalse(self.policy.tool_allowed(None))

        self.assertEqual(self.policy.tool_permission("read_file"), "read")
        self.assertEqual(self.policy.tool_permission("write_file"), "write")
        self.assertIsNone(self.policy.tool_permission(None))

    def test_confirmation_rules(self):
        self.assertFalse(self.policy.requires_confirmation("read_file"))
        self.assertTrue(self.policy.requires_confirmation("write_file"))
        self.assertTrue(self.policy.requires_confirmation("run_command"))
        self.assertTrue(self.policy.requires_confirmation("delete_file"))
        self.assertFalse(self.policy.requires_confirmation("unknown_tool"))
        self.assertFalse(self.policy.requires_confirmation(None))

    # ---------------------------------------------------------
    # Path handling
    # ---------------------------------------------------------

    def test_path_allowed(self):
        self.assertTrue(self.policy.path_allowed(self.workspace))
        self.assertTrue(self.policy.path_allowed(self.workspace / "test.txt"))
        self.assertFalse(self.policy.path_allowed(Path.home()))
        self.assertFalse(self.policy.path_allowed(Path("/etc")))

    def test_path_allowed_exception(self):
        with patch.object(Path, "resolve", side_effect=OSError):
            self.assertFalse(self.policy.path_allowed(self.workspace))

    def test_resolve_path(self):
        self.assertIsNotNone(self.policy.resolve_path("."))
        self.assertIsNotNone(self.policy.resolve_path("test.txt"))

        self.assertIsNone(self.policy.resolve_path(None))
        self.assertIsNone(self.policy.resolve_path("\x00bad"))
        self.assertIsNone(
            self.policy.resolve_path("x" * (self.policy.max_path_length + 1))
        )

    # ---------------------------------------------------------
    # Sensitive paths
    # ---------------------------------------------------------

    def test_sensitive_paths(self):
        self.assertTrue(
            self.policy.is_sensitive_path(Path("/etc/passwd"))
        )
        self.assertTrue(
            self.policy.is_sensitive_path(self.workspace / ".env")
        )
        self.assertTrue(
            self.policy.is_sensitive_path(self.workspace / ".ssh" / "id_rsa")
        )
        self.assertTrue(
            self.policy.is_sensitive_path(self.workspace / "secret.pem")
        )
        self.assertFalse(
            self.policy.is_sensitive_path(self.workspace / "normal.txt")
        )

    def test_sensitive_path_exception(self):
        with patch.object(Path, "resolve", side_effect=OSError):
            self.assertTrue(
                self.policy.is_sensitive_path(self.workspace / "x")
            )

    def test_validate_file_path(self):
        valid = self.policy.validate_file_path("normal.txt")
        self.assertIsNotNone(valid)

        self.assertIsNone(
            self.policy.validate_file_path(".env")
        )
        self.assertIsNone(
            self.policy.validate_file_path("../outside.txt")
        )
        self.assertIsNone(
            self.policy.validate_file_path("/etc/passwd")
        )

    # ---------------------------------------------------------
    # Search pattern validation
    # ---------------------------------------------------------

    def test_validate_search_pattern(self):
        self.assertFalse(self.policy.validate_search_pattern(None))
        self.assertFalse(self.policy.validate_search_pattern(""))
        self.assertFalse(
            self.policy.validate_search_pattern(
                "x" * (self.policy.max_search_pattern_length + 1)
            )
        )
        self.assertFalse(
            self.policy.validate_search_pattern("abc\x00def")
        )
        self.assertTrue(self.policy.validate_search_pattern("abc"))
        self.assertTrue(self.policy.validate_search_pattern("*.py"))

    # ---------------------------------------------------------
    # Command parsing
    # ---------------------------------------------------------

    def test_parse_command(self):
        self.assertEqual(
            self.policy.parse_command("ls -la"),
            ["ls", "-la"],
        )

        self.assertEqual(
            self.policy.parse_command(""),
            None,
        )

        self.assertEqual(
            self.policy.parse_command("   "),
            None,
        )

        self.assertIsNone(
            self.policy.parse_command("echo\x00test")
        )

        self.assertIsNone(
            self.policy.parse_command("echo 'unterminated")
        )

        self.assertIsNone(
            self.policy.parse_command("x" * (self.policy.max_command_length + 1))
        )

    # ---------------------------------------------------------
    # Forbidden command paths
    # ---------------------------------------------------------

    def test_forbidden_command_paths(self):
        self.assertTrue(
            self.policy._command_has_forbidden_path(
                ["cat", "/etc/passwd"]
            )
        )
        self.assertTrue(
            self.policy._command_has_forbidden_path(
                ["cat", "/data/data/test"]
            )
        )
        self.assertTrue(
            self.policy._command_has_forbidden_path(
                ["cat", "/data/user/0/test"]
            )
        )
        self.assertTrue(
            self.policy._command_has_forbidden_path(
                ["cat", "../secret"]
            )
        )
        self.assertTrue(
            self.policy._command_has_forbidden_path(
                ["cat", "bad\x00path"]
            )
        )
        self.assertTrue(
            self.policy._command_has_forbidden_path(
                ["cat", None]
            )
        )
        self.assertFalse(
            self.policy._command_has_forbidden_path(
                ["cat", "normal.txt"]
            )
        )

    # ---------------------------------------------------------
    # Git policy
    # ---------------------------------------------------------

    def test_git_policy(self):
        self.assertFalse(
            self.policy._git_command_allowed(None)
        )
        self.assertFalse(
            self.policy._git_command_allowed(["git"])
        )
        self.assertFalse(
            self.policy._git_command_allowed(["git", "push"])
        )
        self.assertFalse(
            self.policy._git_command_allowed(
                ["git", "status", "--config"]
            )
        )
        self.assertFalse(
            self.policy._git_command_allowed(
                ["git", "status", "--exec"]
            )
        )
        self.assertFalse(
            self.policy._git_command_allowed(
                ["git", "status", "../outside"]
            )
        )
        self.assertFalse(
            self.policy._git_command_allowed(
                ["git", "status", ";rm"]
            )
        )
        self.assertFalse(
            self.policy._git_command_allowed(
                ["git", "status", None]
            )
        )

        self.assertTrue(
            self.policy._git_command_allowed(["git", "status"])
        )
        self.assertTrue(
            self.policy._git_command_allowed(["git", "log"])
        )
        self.assertTrue(
            self.policy._git_command_allowed(["git", "diff"])
        )

    # ---------------------------------------------------------
    # command_allowed
    # ---------------------------------------------------------

    def test_command_allowed_basic(self):
        self.assertTrue(self.policy.command_allowed("ls"))
        self.assertTrue(self.policy.command_allowed("pwd"))
        self.assertTrue(self.policy.command_allowed("echo hello"))

        self.assertFalse(self.policy.command_allowed("rm"))
        self.assertFalse(
            self.policy.command_allowed("unknown_command")
        )

    def test_command_allowed_file_protection(self):
        self.assertFalse(
            self.policy.command_allowed("cat /etc/passwd")
        )
        self.assertFalse(
            self.policy.command_allowed("cat .env")
        )
        self.assertTrue(
            self.policy.command_allowed("cat normal.txt")
        )

    def test_command_allowed_python(self):
        self.assertTrue(
            self.policy.command_allowed("python coverage_test.py")
        )

        self.assertFalse(
            self.policy.command_allowed("python")
        )
        self.assertFalse(
            self.policy.command_allowed("python -c test.py")
        )
        self.assertFalse(
            self.policy.command_allowed("python -m module")
        )
        self.assertFalse(
            self.policy.command_allowed("python -i test.py")
        )
        self.assertFalse(
            self.policy.command_allowed("python test.txt")
        )
        self.assertFalse(
            self.policy.command_allowed("python /etc/test.py")
        )
        self.assertFalse(
            self.policy.command_allowed("python ../test.py")
        )

    def test_command_allowed_git(self):
        self.assertTrue(
            self.policy.command_allowed("git status")
        )
        self.assertTrue(
            self.policy.command_allowed("git log")
        )
        self.assertFalse(
            self.policy.command_allowed("git push")
        )
        self.assertFalse(
            self.policy.command_allowed("git status --config")
        )

    def test_command_allowed_python_resolve_exception(self):
        with patch.object(Path, "resolve", side_effect=OSError):
            self.assertFalse(
                self.policy.command_allowed("python coverage_test.py")
            )

    # ---------------------------------------------------------
    # Generic tool arguments
    # ---------------------------------------------------------

    def test_validate_tool_arguments_global(self):
        self.assertFalse(
            self.policy.validate_tool_arguments(None, {})
        )
        self.assertFalse(
            self.policy.validate_tool_arguments(
                "unknown_tool", {}
            )
        )
        self.assertFalse(
            self.policy.validate_tool_arguments(
                "read_file", None
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "read_file",
                {1: "value"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "read_file",
                {"x" * 101: "value"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "read_file",
                {"path": "\x00bad"},
            )
        )

    # ---------------------------------------------------------
    # Path tool arguments
    # ---------------------------------------------------------

    def test_path_tool_arguments(self):
        path_tools = [
            "list_files",
            "read_file",
            "write_file",
            "create_directory",
            "delete_file",
            "verify_file",
        ]

        for tool in path_tools:
            self.assertFalse(
                self.policy.validate_tool_arguments(tool, {})
            )

        self.assertTrue(
            self.policy.validate_tool_arguments(
                "read_file",
                {"path": "normal.txt"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "read_file",
                {"path": None},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "read_file",
                {"path": "../outside"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "read_file",
                {"path": "/etc/passwd"},
            )
        )

    # ---------------------------------------------------------
    # write_file
    # ---------------------------------------------------------

    def test_write_file_arguments(self):
        self.assertTrue(
            self.policy.validate_tool_arguments(
                "write_file",
                {
                    "path": "normal.txt",
                    "content": "hello",
                },
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "write_file",
                {"path": "normal.txt"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "write_file",
                {
                    "path": "normal.txt",
                    "content": None,
                },
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "write_file",
                {
                    "path": "normal.txt",
                    "content": "x" * 2_000_001,
                },
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "write_file",
                {
                    "path": "",
                    "content": "hello",
                },
            )
        )

    # ---------------------------------------------------------
    # search_files
    # ---------------------------------------------------------

    def test_search_files_arguments(self):
        self.assertTrue(
            self.policy.validate_tool_arguments(
                "search_files",
                {"pattern": "*.py"},
            )
        )

        self.assertTrue(
            self.policy.validate_tool_arguments(
                "search_files",
                {
                    "pattern": "*.py",
                    "path": ".",
                    "max_matches": 5,
                },
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "search_files",
                {"pattern": None},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "search_files",
                {"pattern": ""},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "search_files",
                {
                    "pattern": "x" * (
                        self.policy.max_search_pattern_length + 1
                    )
                },
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "search_files",
                {"pattern": "bad\x00pattern"},
            )
        )

        for value in [0, -1, True, "5"]:
            self.assertFalse(
                self.policy.validate_tool_arguments(
                    "search_files",
                    {
                        "pattern": "*.py",
                        "max_matches": value,
                    },
                )
            )

    # ---------------------------------------------------------
    # remember_fact
    # ---------------------------------------------------------

    def test_remember_fact_arguments(self):
        self.assertTrue(
            self.policy.validate_tool_arguments(
                "remember_fact",
                {"fact": "ALIX test fact"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "remember_fact",
                {"fact": None},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "remember_fact",
                {"fact": "   "},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "remember_fact",
                {
                    "fact": "x" * (
                        self.policy.max_argument_length + 1
                    )
                },
            )
        )

    # ---------------------------------------------------------
    # run_command
    # ---------------------------------------------------------

    def test_run_command_arguments(self):
        self.assertTrue(
            self.policy.validate_tool_arguments(
                "run_command",
                {"command": "ls"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "run_command",
                {"command": None},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "run_command",
                {"command": "rm -rf /"},
            )
        )

    # ---------------------------------------------------------
    # run_python
    # ---------------------------------------------------------

    def test_run_python_arguments(self):
        self.assertTrue(
            self.policy.validate_tool_arguments(
                "run_python",
                {"script_path": "coverage_test.py"},
            )
        )

        invalid = [
            None,
            "",
            "/etc/test.py",
            "../test.py",
            "coverage_test.txt",
        ]

        for value in invalid:
            self.assertFalse(
                self.policy.validate_tool_arguments(
                    "run_python",
                    {"script_path": value},
                )
            )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "run_python",
                {
                    "script_path": "x" * (
                        self.policy.max_path_length + 1
                    )
                },
            )
        )

    # ---------------------------------------------------------
    # validate_command_arguments
    # ---------------------------------------------------------

    def test_validate_command_arguments(self):
        self.assertTrue(
            self.policy.validate_command_arguments(
                {"command": "ls"}
            )
        )

        self.assertFalse(
            self.policy.validate_command_arguments(None)
        )

        self.assertFalse(
            self.policy.validate_command_arguments(
                {i: "value" for i in range(17)}
            )
        )

        self.assertFalse(
            self.policy.validate_command_arguments(
                {1: "value"}
            )
        )

        self.assertFalse(
            self.policy.validate_command_arguments(
                {"x" * 101: "value"}
            )
        )

        self.assertFalse(
            self.policy.validate_command_arguments(
                {"command": "x" * 2_000_001}
            )
        )

        self.assertFalse(
            self.policy.validate_command_arguments(
                {"command": "bad\x00command"}
            )
        )

    # ---------------------------------------------------------
    # Security summary
    # ---------------------------------------------------------

    def test_security_summary(self):
        summary = self.policy.security_summary()

        self.assertEqual(
            summary["workspace"],
            str(self.policy.workspace),
        )

        for key in [
            "workspace_isolation",
            "symlink_escape_protection",
            "sensitive_file_protection",
            "command_allowlist",
            "blocked_command_list",
            "git_restricted",
            "python_restricted",
            "confirmation_required",
            "destructive_confirmation",
        ]:
            self.assertTrue(summary[key])

        self.assertEqual(
            summary["max_command_length"],
            self.policy.max_command_length,
        )
        self.assertEqual(
            summary["max_path_length"],
            self.policy.max_path_length,
        )
        self.assertEqual(
            summary["max_search_pattern_length"],
            self.policy.max_search_pattern_length,
        )
        self.assertEqual(
            summary["max_search_matches"],
            self.policy.max_search_matches,
        )


    # ---------------------------------------------------------
    # Remaining defensive branches
    # ---------------------------------------------------------

    def test_git_absolute_path_branch(self):
        self.assertFalse(
            self.policy._git_command_allowed(
                ["git", "status", "/workspace/file"]
            )
        )

    def test_validate_path_tool_path_allowed_failure(self):
        with patch.object(
            self.policy,
            "path_allowed",
            return_value=False,
        ):
            self.assertFalse(
                self.policy.validate_tool_arguments(
                    "read_file",
                    {"path": "normal.txt"},
                )
            )

    def test_write_file_type_and_length_guards(self):
        self.assertFalse(
            self.policy.validate_tool_arguments(
                "write_file",
                {"path": None, "content": "x"},
            )
        )

        self.assertFalse(
            self.policy.validate_tool_arguments(
                "write_file",
                {
                    "path": "x" * (self.policy.max_path_length + 1),
                    "content": "x",
                },
            )
        )

    def test_search_nul_branch(self):
        self.assertFalse(
            self.policy.validate_tool_arguments(
                "search_files",
                {"pattern": "abc\x00def"},
            )
        )

    def test_remember_fact_length_branch(self):
        self.assertFalse(
            self.policy.validate_tool_arguments(
                "remember_fact",
                {
                    "fact": "x" * (
                        self.policy.max_argument_length + 1
                    )
                },
            )
        )

    def test_run_python_remaining_guards(self):
        with patch.object(
            self.policy,
            "path_allowed",
            return_value=False,
        ):
            self.assertFalse(
                self.policy.validate_tool_arguments(
                    "run_python",
                    {"script_path": "coverage_test.py"},
                )
            )

        with patch.object(
            self.policy,
            "is_sensitive_path",
            return_value=True,
        ):
            self.assertFalse(
                self.policy.validate_tool_arguments(
                    "run_python",
                    {"script_path": "coverage_test.py"},
                )
            )

        with patch.object(
            self.policy,
            "resolve_path",
            return_value=self.workspace / "coverage_test.txt",
        ):
            self.assertFalse(
                self.policy.validate_tool_arguments(
                    "run_python",
                    {"script_path": "coverage_test.txt"},
                )
            )

    def test_command_file_argument_flag(self):
        self.assertTrue(
            self.policy.command_allowed("cat -n normal.txt")
        )

    def test_command_forbidden_file_argument_type(self):
        with patch.object(
            self.policy,
            "parse_command",
            return_value=["cat", None],
        ):
            self.assertFalse(
                self.policy.command_allowed("cat normal.txt")
            )

    def test_command_file_argument_resolve_failure(self):
        with patch.object(
            self.policy,
            "resolve_path",
            return_value=None,
        ):
            self.assertFalse(
                self.policy.command_allowed("cat normal.txt")
            )

    def test_command_python_path_restrictions(self):
        with patch.object(
            self.policy,
            "path_allowed",
            return_value=False,
        ):
            self.assertFalse(
                self.policy.command_allowed(
                    "python coverage_test.py"
                )
            )

        with patch.object(
            self.policy,
            "is_sensitive_path",
            return_value=True,
        ):
            self.assertFalse(
                self.policy.command_allowed(
                    "python coverage_test.py"
                )
            )


if __name__ == "__main__":
    unittest.main()

# ============================================================
# V9 - Remaining defensive branches
# ============================================================

class TestPolicyCoverageV9(unittest.TestCase):

    def setUp(self):
        self.policy = Policy()

    def test_validate_tool_arguments_too_many_arguments(self):
        args = {f"k{i}": "v" for i in range(17)}
        self.assertFalse(
            self.policy.validate_tool_arguments("list_files", args)
        )

    def test_validate_file_path_sensitive_rejected(self):
        self.assertIsNone(
            self.policy.validate_file_path(".env")
        )

    def test_parse_command_non_string(self):
        self.assertIsNone(self.policy.parse_command(None))

    def test_parse_command_too_many_arguments(self):
        command = "echo " + " ".join(f"x{i}" for i in range(40))
        self.assertIsNone(self.policy.parse_command(command))

    def test_parse_command_argument_too_long(self):
        command = "echo " + ("x" * (self.policy.max_argument_length + 1))
        self.assertIsNone(self.policy.parse_command(command))

    def test_parse_command_empty_after_split(self):
        with patch("core.policy.shlex.split", return_value=[]):
            self.assertIsNone(self.policy.parse_command("echo test"))

    def test_parse_command_nul_after_split(self):
        with patch("core.policy.shlex.split", return_value=["echo", "\x00"]):
            self.assertIsNone(self.policy.parse_command("echo test"))

    def test_validate_tool_arguments_non_string_tool(self):
        self.assertFalse(
            self.policy.validate_tool_arguments(
                None,
                {}
            )
        )

    def test_validate_tool_arguments_non_dict(self):
        self.assertFalse(
            self.policy.validate_tool_arguments(
                "list_files",
                []
            )
        )


if __name__ == "__main__":
    unittest.main()
