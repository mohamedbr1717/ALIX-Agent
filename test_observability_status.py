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

        return agent, log_file

    @staticmethod
    def records(log_file):
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

            result = agent.execute_tool(
                "run_command",
                {"command": "true"},
            )

            self.assertTrue(result["ok"])

            finished = [
                r for r in self.records(log_file)
                if r["event"] == "tool_finished"
            ]

            self.assertEqual(len(finished), 1)
            self.assertEqual(
                finished[0]["status"],
                "finished",
            )

    def test_failure_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, log_file = self.make_agent(tmp)

            result = agent.execute_tool(
                "run_command",
                {"command": "false"},
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

            agent.executor.command_timeout = 1

            result = agent.execute_tool(
                "run_command",
                {
                    "command": "python -c \"import time; time.sleep(2)\""
                },
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
                side_effect=RuntimeError("TEST_EXCEPTION"),
            ):
                result = agent.execute_tool(
                    "system_info",
                    {},
                )

            self.assertFalse(result["ok"])

            finished = [
                r for r in self.records(log_file)
                if r["event"] == "tool_finished"
            ]

            self.assertEqual(len(finished), 1)
            self.assertEqual(
                finished[0]["status"],
                "exception",
            )

    def test_request_and_execution_correlation(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, log_file = self.make_agent(tmp)

            agent.execute_tool(
                "run_command",
                {"command": "true"},
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

            self.assertIn(
                "latency_ms",
                finish,
            )


if __name__ == "__main__":
    unittest.main()
