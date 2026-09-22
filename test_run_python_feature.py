"""Feature tests for the run_python vertical slice migration."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.executor import SafeExecutor
from core.policy import Policy
from core.sandbox import SandboxUnavailable

from features.command_execution.application.dto.run_python import RunPythonDTO
from features.command_execution.application.use_cases.run_python import (
    RunPythonUseCase,
)
from features.command_execution.composition import (
    build_run_python_controller,
)
from features.command_execution.infrastructure.adapters.policy_script_authorization import (
    PolicyScriptAuthorizationAdapter,
)


class FakeSandbox:
    """Test double for ProotSandbox: no real isolation, canned result."""

    def __init__(self, workspace=None):
        self.workspace = workspace

    def run(self, script_path=None, timeout=None, env=None):
        return {
            "ok": True,
            "stdout": "FAKE_STDOUT",
            "stderr": "",
            "return_code": 0,
            "timed_out": False,
        }


class UnavailableSandbox:
    """Test double whose construction fails: exercises fail-closed."""

    def __init__(self, workspace=None):
        raise SandboxUnavailable("proot غير مثبت في بيئة الاختبار")


def make_policy(tmp):
    policy = Policy()
    policy.workspace = Path(tmp).resolve()
    return policy


class TestRunPythonFeature(unittest.TestCase):
    def test_controller_wires_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            (Path(tmp) / "hello.py").write_text(
                "print('hi')\n", encoding="utf-8"
            )

            controller = build_run_python_controller(policy)
            with patch("core.executor.ProotSandbox", FakeSandbox):
                result = controller.handle({"script_path": "hello.py"})

            self.assertTrue(result["ok"])
            self.assertIn("FAKE_STDOUT", result.get("stdout", ""))
            evidence = result.get("evidence", {})
            self.assertTrue(evidence.get("sandboxed"))
            self.assertEqual(evidence.get("isolation"), "proot")

    def test_empty_script_path_denied_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_run_python_controller(make_policy(tmp))
            result = controller.handle({})
            self.assertFalse(result["ok"])

    def test_sensitive_path_denied_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            calls = []

            class SpyRunner:
                def run_script(self, script_path):
                    calls.append(script_path)
                    return {"ok": True}

            use_case = RunPythonUseCase(
                authorization=PolicyScriptAuthorizationAdapter(policy),
                runner=SpyRunner(),
            )
            result = use_case.execute(
                RunPythonDTO(script_path="../outside.py")
            )

            self.assertFalse(result["ok"])
            self.assertEqual(calls, [])

    def test_nonexistent_script_fails_in_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_run_python_controller(make_policy(tmp))
            result = controller.handle({"script_path": "missing.py"})
            self.assertFalse(result["ok"])

    def test_non_py_suffix_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            (Path(tmp) / "notes.txt").write_text("x", encoding="utf-8")

            controller = build_run_python_controller(policy)
            result = controller.handle({"script_path": "notes.txt"})

            self.assertFalse(result["ok"])
            self.assertIn(".py", result.get("message", ""))

    def test_sandbox_unavailable_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            (Path(tmp) / "hello.py").write_text(
                "print('hi')\n", encoding="utf-8"
            )

            controller = build_run_python_controller(policy)
            with patch("core.executor.ProotSandbox", UnavailableSandbox):
                result = controller.handle({"script_path": "hello.py"})

            self.assertFalse(result["ok"])
            self.assertIn("العزل", result.get("message", ""))

    def test_old_new_parity(self):
        battery = [
            ("", "empty-path"),
            ("missing.py", "nonexistent"),
            ("../outside.py", "outside-workspace"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            (Path(tmp) / "notes.txt").write_text("x", encoding="utf-8")
            battery.append(("notes.txt", "non-py-suffix"))
            (Path(tmp) / "hello.py").write_text(
                "print('hi')\n", encoding="utf-8"
            )

            executor = SafeExecutor(policy)
            controller = build_run_python_controller(policy)

            for script_path, label in battery:
                with self.subTest(label=label):
                    old = executor.run_python(script_path)
                    new = controller.handle({"script_path": script_path})
                    self.assertEqual(
                        old["ok"],
                        new["ok"],
                        f"parity failed for {label}",
                    )

            with patch("core.executor.ProotSandbox", FakeSandbox):
                old = executor.run_python("hello.py")
                new = controller.handle({"script_path": "hello.py"})
            self.assertEqual(old["ok"], new["ok"])
            self.assertTrue(new["ok"])


if __name__ == "__main__":
    unittest.main()
