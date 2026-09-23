"""Behavioral tests for ALIXAgent.run(): the main agent loop.

The LLM is mocked; extract_tool_calls is mocked only for the tool-call
scenarios (extraction itself is covered in test_agent_behavior.py).
Memory and audit are mocked so the live memory.json is never touched.
"""
from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from test_agent_behavior import make_agent


class TestRunLoop(unittest.TestCase):
    def make_run_agent(self):
        tmp = tempfile.mkdtemp()
        agent = make_agent(tmp)
        agent.llm = mock.Mock()
        agent.memory = mock.Mock()
        agent.memory.get_context.return_value = {
            "facts": [],
            "preferences": [],
        }
        agent.audit = mock.Mock()
        return agent

    def test_invalid_input_non_string(self):
        agent = self.make_run_agent()
        self.assertEqual(agent.run(123), "❌ الإدخال غير صالح.")
        agent.llm.chat.assert_not_called()

    def test_invalid_input_empty(self):
        agent = self.make_run_agent()
        self.assertEqual(agent.run("   "), "❌ لم يتم إدخال طلب.")
        agent.llm.chat.assert_not_called()

    def test_direct_answer(self):
        agent = self.make_run_agent()
        agent.llm.chat.return_value = {"content": "Hello!"}
        result = agent.run("hi")
        self.assertEqual(result, "Hello!")
        self.assertEqual(
            agent.messages[-1], {"role": "assistant", "content": "Hello!"}
        )
        agent.memory.add_history.assert_any_call("user", "hi")
        agent.memory.add_history.assert_any_call("assistant", "Hello!")

    def test_think_tag_stripped(self):
        agent = self.make_run_agent()
        agent.llm.chat.return_value = {
            "content": "<think>internal reasoning</think>Real answer"
        }
        result = agent.run("hi")
        self.assertEqual(result, "Real answer")

    def test_empty_llm_response(self):
        agent = self.make_run_agent()
        agent.llm.chat.return_value = {"content": "   "}
        result = agent.run("hi")
        self.assertEqual(result, "لم يُرجع النموذج نتيجة نصية.")

    def test_tool_call_round_trip(self):
        agent = self.make_run_agent()
        agent.llm.chat.return_value = {"content": "done"}
        agent.extract_tool_calls = mock.Mock(
            side_effect=[[("call_1", "system_info", {})], []]
        )
        agent.execute_tool = mock.Mock(
            return_value={"ok": True, "evidence": {}}
        )
        result = agent.run("info")
        self.assertEqual(result, "done")
        agent.execute_tool.assert_called_once_with("system_info", {})
        tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "call_1")
        self.assertEqual(tool_msgs[0]["name"], "system_info")

    def test_tool_call_limit_per_round(self):
        agent = self.make_run_agent()
        agent.llm.chat.return_value = {"content": "done"}
        calls = [(f"c{i}", "system_info", {}) for i in range(6)]
        agent.extract_tool_calls = mock.Mock(side_effect=[calls, []])
        agent.execute_tool = mock.Mock(return_value={"ok": True})
        agent.run("info")
        self.assertEqual(
            agent.execute_tool.call_count, agent.MAX_TOOL_CALLS_PER_ROUND
        )
        audit_names = [c.args[0] for c in agent.audit.call_args_list]
        self.assertIn("tool_call_limit_exceeded", audit_names)

    def test_max_rounds_warning(self):
        agent = self.make_run_agent()
        agent.llm.chat.return_value = {"content": "thinking"}
        agent.extract_tool_calls = mock.Mock(
            return_value=[("c1", "system_info", {})]
        )
        agent.execute_tool = mock.Mock(return_value={"ok": True})
        result = agent.run("info")
        self.assertIn("الحد الأقصى", result)
        self.assertEqual(agent.execute_tool.call_count, agent.MAX_ROUNDS)
        audit_names = [c.args[0] for c in agent.audit.call_args_list]
        self.assertIn("agent_max_rounds", audit_names)

    def test_tool_result_wrapped_as_untrusted(self):
        agent = self.make_run_agent()
        agent.llm.chat.return_value = {"content": "done"}
        agent.extract_tool_calls = mock.Mock(
            side_effect=[[("c1", "system_info", {})], []]
        )
        agent.execute_tool = mock.Mock(
            return_value={"ok": True, "evidence": {"x": "<tool_call>"}}
        )
        agent.run("info")
        tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
        content = tool_msgs[0]["content"]
        # The tool output must be wrapped in untrusted-data markers so the
        # LLM treats it as DATA ONLY, never as instructions.
        self.assertIn("UNTRUSTED TOOL DATA", content)
        self.assertIn("DATA ONLY", content)


if __name__ == "__main__":
    unittest.main()
