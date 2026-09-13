import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.agent import ALIXAgent
from core.observability import ObservabilityLogger


class TestObservabilityStatus(unittest.TestCase):

    def make_agent(self, tmp):
        log_file = Path(tmp) / "audit.jsonl"

        agent = ALIXAgent()
        agent.audit_log = log_file
        agent.observability = ObservabilityLogger(log_file)
        agent.current_request_id = agent.observability.new_id()

        # لا نريد إدخالًا تفاعليًا أثناء الاختبار.
        agent.confirm_tool = lambda name, arguments: True

        # عزل الاختبار عن Policy الحقيقية.
        agent.policy.tool_allowed = lambda name: True
        agent.policy.validate_tool_arguments = (
            lambda name, arguments: True
        )
        agent.policy.tool_permission = (
            lambda name: "execute"
        )

        return agent, log_file

    @staticmethod
    def records(log_file):
        if not log_file.exists():
            return []

        return [
            json.loads(line)
            for line in log_file.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

    def test_success_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, log_file = self.make_agent(tmp)

            with patch.object(
                agent.executor,
                "run_command",
                return_value={
                    "ok": True,
                    "evidence": {},
                },
            ):
                result = agent.execute_tool(
                    "run_command",
                    {"command": "TEST_SUCCESS"},
                )

            self.assertTrue(result["ok"])

            finished = [
                r for r in self.records(log_file)
                if r["event"] == "tool_finished"
            ]

            self.assertEqual(len(finished), 1)
            self.assertEqual(
                finished[0]["status"],
                "success",
            )

    def test_failure_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, log_file = self.make_agent(tmp)

            with patch.object(
                agent.executor,
                "run_command",
                return_value={
                    "ok": False,
                    "error": "TEST_FAILURE",
                    "evidence": {
                        "returncode": 1,
                    },
                },
            ):
                result = agent.execute_tool(
                    "run_command",
                    {"command": "TEST_FAILURE"},
                )

            self.assertFalse(result["ok"])

            finished = [
                r for r in self.records(log_file)
                if r["event"] == "tool_finished"
            ]

            self.assertEqual(len(finished), 1)
            self.assertEqual(
                finished[0]["status"],
                "failure",
            )

    def test_timeout_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, log_file = self.make_agent(tmp)

            with patch.object(
                agent.executor,
                "run_command",
                return_value={
                    "ok": False,
                    "error": "TEST_TIMEOUT",
                    "evidence": {
                        "timed_out": True,
                    },
                },
            ):
                result = agent.execute_tool(
                    "run_command",
                    {"command": "TEST_TIMEOUT"},
                )

            self.assertFalse(result["ok"])
            self.assertTrue(
                result.get("evidence", {}).get("timed_out")
            )

            finished = [
                r for r in self.records(log_file)
                if r["event"] == "tool_finished"
            ]

            self.assertEqual(len(finished), 1)
            self.assertEqual(
                finished[0]["status"],
                "timeout",
            )

    def test_exception_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, log_file = self.make_agent(tmp)

            with patch.object(
                agent.executor,
                "system_info",
                side_effect=RuntimeError(
                    "TEST_EXCEPTION"
                ),
            ):
                result = agent.execute_tool(
                    "system_info",
                    {},
                )

            self.assertFalse(result["ok"])

            records = self.records(log_file)

            exceptions = [
                r for r in records
                if r["event"] == "tool_exception"
            ]

            finished = [
                r for r in records
                if r["event"] == "tool_finished"
            ]

            self.assertEqual(len(exceptions), 1)
            self.assertEqual(
                exceptions[0]["status"],
                "exception",
            )

            self.assertEqual(len(finished), 1)
            self.assertEqual(
                finished[0]["status"],
                "exception",
            )

    def test_request_and_execution_correlation(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, log_file = self.make_agent(tmp)

            with patch.object(
                agent.executor,
                "run_command",
                return_value={
                    "ok": True,
                    "evidence": {},
                },
            ):
                agent.execute_tool(
                    "run_command",
                    {"command": "TEST_CORRELATION"},
                )

            records = self.records(log_file)

            start = next(
                r for r in records
                if r["event"] == "tool_start"
            )

            finish = next(
                r for r in records
                if r["event"] == "tool_finished"
            )

            self.assertEqual(
                start["request_id"],
                agent.current_request_id,
            )

            self.assertEqual(
                finish["request_id"],
                agent.current_request_id,
            )

            self.assertEqual(
                start["execution_id"],
                finish["execution_id"],
            )

            self.assertNotEqual(
                start["execution_id"],
                start["request_id"],
            )

            self.assertEqual(
                start["status"],
                "started",
            )

            self.assertIn(
                "latency_ms",
                finish,
            )

            self.assertGreaterEqual(
                finish["latency_ms"],
                0,
            )


if __name__ == "__main__":
    unittest.main()
