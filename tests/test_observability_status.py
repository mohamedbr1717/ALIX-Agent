import json
import tempfile
import unittest
from pathlib import Path

from core.agent import ALIXAgent
from core.observability import ObservabilityLogger


class TestObservabilityStatus(unittest.TestCase):

    def make_agent(self, result=None, exception=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        tmp_path = Path(tmp.name)

        agent = ALIXAgent.__new__(ALIXAgent)

        agent.audit_log = tmp_path / "audit.jsonl"
        agent.observability = ObservabilityLogger(agent.audit_log)
        agent.current_request_id = "req-test"

        agent.policy = type(
            "PolicyStub",
            (),
            {
                "tool_allowed": lambda self, name: True,
                "validate_tool_arguments": (
                    lambda self, name, args: True
                ),
                "tool_permission": (
                    lambda self, name: "execute"
                ),
            },
        )()

        agent.confirm_tool = (
            lambda name, arguments: True
        )

        class ExecutorStub:

            def run_command(self, command):
                if exception is not None:
                    raise exception

                return result

        agent.executor = ExecutorStub()

        return agent

    @staticmethod
    def read_events(path):
        return [
            json.loads(line)
            for line in Path(path).read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

    def finished_events(self, agent):
        return [
            event
            for event in self.read_events(
                agent.audit_log
            )
            if event["event"] == "tool_finished"
        ]

    def test_success_status(self):
        agent = self.make_agent(
            result={
                "ok": True,
                "evidence": {},
            }
        )

        result = agent.execute_tool(
            "run_command",
            {"command": "pwd"},
        )

        self.assertTrue(result["ok"])

        finished = self.finished_events(agent)

        self.assertEqual(len(finished), 1)
        self.assertEqual(
            finished[0]["status"],
            "success",
        )

    def test_failure_status(self):
        agent = self.make_agent(
            result={
                "ok": False,
                "error": "command failed",
                "evidence": {
                    "returncode": 1,
                },
            }
        )

        result = agent.execute_tool(
            "run_command",
            {"command": "pwd"},
        )

        self.assertFalse(result["ok"])

        finished = self.finished_events(agent)

        self.assertEqual(len(finished), 1)
        self.assertEqual(
            finished[0]["status"],
            "failure",
        )

    def test_timeout_status(self):
        agent = self.make_agent(
            result={
                "ok": False,
                "error": "timeout",
                "evidence": {
                    "timed_out": True,
                },
            }
        )

        result = agent.execute_tool(
            "run_command",
            {"command": "pwd"},
        )

        self.assertFalse(result["ok"])

        finished = self.finished_events(agent)

        self.assertEqual(len(finished), 1)
        self.assertEqual(
            finished[0]["status"],
            "timeout",
        )

    def test_exception_status(self):
        agent = self.make_agent(
            exception=RuntimeError("boom")
        )

        result = agent.execute_tool(
            "run_command",
            {"command": "pwd"},
        )

        self.assertFalse(result["ok"])

        events = self.read_events(
            agent.audit_log
        )

        exception_events = [
            event
            for event in events
            if event["event"] == "tool_exception"
        ]

        finished = self.finished_events(agent)

        self.assertEqual(
            len(exception_events),
            1,
        )
        self.assertEqual(
            exception_events[0]["status"],
            "exception",
        )

        self.assertEqual(len(finished), 1)
        self.assertEqual(
            finished[0]["status"],
            "exception",
        )

    def test_execution_correlation(self):
        agent = self.make_agent(
            result={
                "ok": True,
                "evidence": {},
            }
        )

        agent.execute_tool(
            "run_command",
            {"command": "pwd"},
        )

        events = self.read_events(
            agent.audit_log
        )

        start = next(
            event
            for event in events
            if event["event"] == "tool_start"
        )

        finish = next(
            event
            for event in events
            if event["event"] == "tool_finished"
        )

        self.assertEqual(
            start["request_id"],
            "req-test",
        )
        self.assertEqual(
            finish["request_id"],
            "req-test",
        )
        self.assertEqual(
            start["execution_id"],
            finish["execution_id"],
        )
        self.assertEqual(
            start["status"],
            "started",
        )
        self.assertGreaterEqual(
            finish["latency_ms"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
