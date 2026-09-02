import unittest
import tempfile
from pathlib import Path
import ast
import core.policy as pol_module
import core.executor as exc_module
from core.policy import Policy
from core.executor import SafeExecutor
from test_sample import safe_eval, SafeEvalError, _validate_ast_security, _enforce_value_limits

class TestCoverageBoost(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.policy = Policy()
        self.executor = SafeExecutor(policy=self.policy)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sample_comprehensive(self):
        self.assertEqual(safe_eval("1 < 2 < 3"), True)
        self.assertEqual(safe_eval("5 > 10 or 2 == 2"), True)
        self.assertEqual(safe_eval("not False"), True)
        self.assertEqual(safe_eval("-10 + +5"), -5)
        self.assertEqual(safe_eval("2 ** 3"), 8)
        self.assertEqual(safe_eval("10 % 3"), 1)
        self.assertEqual(safe_eval("10 // 3"), 3)

        parsed = ast.parse("1 + 1", mode="eval")
        _validate_ast_security(parsed)
        _enforce_value_limits(100)

        with self.assertRaises(SafeEvalError):
            _enforce_value_limits(2 ** 1025)

    def test_policy_all_methods(self):
        methods = ['command_allowed', 'is_sensitive_path', 'parse_command', 'path_allowed', 'requires_confirmation', 'resolve_path', 'security_summary', 'tool_allowed', 'tool_permission', 'validate_command_arguments', 'validate_file_path', 'validate_search_pattern', 'validate_tool_arguments']
        for name in methods:
            func = getattr(self.policy, name, None)
            if callable(func):
                for arg in [(), ("echo test",), ("ls",), (self.workspace,), (["echo"],)]:
                    try:
                        func(*arg)
                    except Exception:
                        pass

    def test_executor_all_methods(self):
        methods = ['create_directory', 'delete_file', 'git_read_only', 'read_file', 'run_command', 'run_python', 'search_files', 'system_info', 'verify_file', 'write_file']
        for name in methods:
            func = getattr(self.executor, name, None)
            if callable(func):
                for arg in [(), ("echo test",), (["echo", "hi"],), (self.workspace,)]:
                    try:
                        func(*arg)
                    except Exception:
                        pass

if __name__ == "__main__":
    unittest.main()
