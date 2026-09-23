"""Behavioral tests for ALIXAgent._apply_context_boundary (P3.9).

The hard guarantee: total context chars never exceed MAX_CONTEXT_CHARS.
Tests use an instance-level MAX_CONTEXT_CHARS override for small,
fast, deterministic scenarios.
"""
from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from test_agent_behavior import make_agent

MARKER = "[P3.9 CONTEXT TRUNCATED]"


def total_chars(messages) -> int:
    return sum(len(m.get("content", "")) for m in messages
               if isinstance(m.get("content", ""), str))


class TestContextBoundary(unittest.TestCase):
    def make_ctx_agent(self, limit: int = 1000):
        agent = make_agent(tempfile.mkdtemp())
        agent.audit = mock.Mock()
        agent.MAX_CONTEXT_CHARS = limit
        return agent

    def test_noop_under_limit(self):
        agent = self.make_ctx_agent(limit=1000)
        agent.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        before = [dict(m) for m in agent.messages]
        agent._apply_context_boundary()
        self.assertEqual(agent.messages, before)
        agent.audit.assert_not_called()

    def test_tool_data_truncated_first(self):
        agent = self.make_ctx_agent(limit=1000)
        agent.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u" * 100},
            {"role": "tool", "content": "t" * 2000},
        ]
        agent._apply_context_boundary()
        # Tool message truncated with marker; user message untouched.
        self.assertEqual(agent.messages[1]["content"], "u" * 100)
        self.assertIn(MARKER, agent.messages[2]["content"])
        self.assertLess(len(agent.messages[2]["content"]), 2000)
        self.assertLessEqual(total_chars(agent.messages), 1000)

    def test_marker_only_when_budget_tiny(self):
        agent = self.make_ctx_agent(limit=500)
        agent.messages = [
            {"role": "system", "content": "s" * 10},
            {"role": "tool", "content": "t" * 1000},
        ]
        # excess=510 -> new_length=460 <= 512 -> marker replaces content.
        agent._apply_context_boundary()
        content = agent.messages[1]["content"]
        self.assertIn(MARKER, content)
        self.assertNotIn("t" * 10, content)
        self.assertLessEqual(total_chars(agent.messages), 500)

    def test_phase2_truncates_oldest_non_system(self):
        agent = self.make_ctx_agent(limit=1000)
        agent.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u" * 2000},
        ]
        agent._apply_context_boundary()
        # No tool messages: phase 2 truncates the user message.
        self.assertEqual(agent.messages[0]["content"], "sys")
        self.assertIn(MARKER, agent.messages[1]["content"])
        self.assertLessEqual(total_chars(agent.messages), 1000)

    def test_system_message_never_truncated(self):
        agent = self.make_ctx_agent(limit=1000)
        sys_content = "s" * 500
        agent.messages = [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": "u" * 2000},
        ]
        agent._apply_context_boundary()
        self.assertEqual(agent.messages[0]["content"], sys_content)
        self.assertLessEqual(total_chars(agent.messages), 1000)

    def test_oversized_system_raises_fail_closed(self):
        agent = self.make_ctx_agent(limit=1000)
        agent.messages = [
            {"role": "system", "content": "s" * 5000},
            {"role": "user", "content": "hi"},
        ]
        # System is untouchable in all phases: the hard invariant
        # must fail closed rather than silently exceed the limit.
        with self.assertRaises(RuntimeError):
            agent._apply_context_boundary()

    def test_invariant_holds_under_pressure(self):
        agent = self.make_ctx_agent(limit=1000)
        agent.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u" * 5000},
            {"role": "tool", "content": "t" * 5000},
            {"role": "assistant", "content": "a" * 5000},
            {"role": "tool", "content": "t" * 5000},
        ]
        agent._apply_context_boundary()
        self.assertLessEqual(total_chars(agent.messages), 1000)
        self.assertEqual(agent.messages[0]["content"], "sys")

    def test_audit_logged_on_truncation(self):
        agent = self.make_ctx_agent(limit=1000)
        agent.messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "t" * 5000},
        ]
        agent._apply_context_boundary()
        agent.audit.assert_called_once()
        name, payload = agent.audit.call_args[0]
        self.assertEqual(name, "context_boundary_applied")
        self.assertTrue(payload["truncated"])
        self.assertTrue(payload["within_limit"])
        self.assertGreater(payload["before_chars"], payload["after_chars"])


if __name__ == "__main__":
    unittest.main()
