"""Behavioral tests for core/dual_llm.py — task router + sensitivity gating.

No real network: both engines are stubbed. Every test asserts a real
routing guarantee (where the request went, what never left the device).
"""
from __future__ import annotations

import unittest

from core.dual_llm import (
    DualLLM,
    FAIL_CLOSED_REFUSAL,
    LOCAL_TASKS,
    detect_sensitive,
    route,
)


class StubEngine:
    """Minimal engine double: records calls, returns canned replies."""

    def __init__(self, reply="stub-reply", fail=False):
        self.calls = []
        self.reply = reply
        self.fail = fail

    def chat(self, messages, tools=None):
        self.calls.append(
            {"messages": messages, "tools": tools}
        )

        if self.fail:
            return {
                "role": "assistant",
                "content": "❌ stub failure",
            }

        return {
            "role": "assistant",
            "content": self.reply,
        }

    def status(self):
        return {"stub": True}


def make_dual(local=None, hybrid=None, audit_fn=None):
    return DualLLM(
        local=local or StubEngine(reply="local-reply"),
        hybrid=hybrid or StubEngine(reply="remote-reply"),
        audit_fn=audit_fn,
    )


def all_texts(calls):
    texts = []

    for call in calls:

        for message in call["messages"]:

            content = message.get("content", "")

            if isinstance(content, str):
                texts.append(content)

    return "\n".join(texts)


class TestRoutePure(unittest.TestCase):
    def test_tools_go_remote(self):
        engine, reason = route(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function"}],
        )
        self.assertEqual(engine, "remote")
        self.assertIn("tool", reason)

    def test_local_tasks_go_local(self):
        for task in LOCAL_TASKS:
            engine, _ = route(
                [{"role": "user", "content": "hi"}],
                task=task,
            )
            self.assertEqual(
                engine, "local", f"task={task}"
            )

    def test_unknown_task_defaults_remote(self):
        engine, _ = route(
            [{"role": "user", "content": "hi"}],
            task="write me a novel",
        )
        self.assertEqual(engine, "remote")

    def test_plain_prompt_defaults_remote(self):
        # Preserves current behavior: no silent heuristics.
        engine, reason = route(
            [{"role": "user", "content": "short"}]
        )
        self.assertEqual(engine, "remote")

    def test_sensitive_flag_beats_tools(self):
        engine, _ = route(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function"}],
            sensitive=True,
        )
        self.assertEqual(engine, "local")

    def test_deterministic(self):
        kwargs = dict(
            tools=[{"type": "function"}],
            task="summarize",
            sensitive=True,
        )
        messages = [
            {"role": "user", "content": "sk-abc123XYZ"}
        ]
        self.assertEqual(
            route(messages, **kwargs),
            route(messages, **kwargs),
        )


class TestDetectSensitive(unittest.TestCase):
    def test_api_key_detected(self):
        self.assertTrue(
            detect_sensitive(
                [
                    {
                        "role": "user",
                        "content": (
                            "my key is sk-abcdefgh12345678 "
                            "keep it"
                        ),
                    }
                ]
            )
        )

    def test_github_token_detected(self):
        self.assertTrue(
            detect_sensitive(
                [
                    {
                        "role": "user",
                        "content": "ghp_1234567890abcdef",
                    }
                ]
            )
        )

    def test_password_assignment_detected(self):
        self.assertTrue(
            detect_sensitive(
                [
                    {
                        "role": "user",
                        "content": "password: s3cr3t!",
                    }
                ]
            )
        )

    def test_private_key_detected(self):
        self.assertTrue(
            detect_sensitive(
                [
                    {
                        "role": "user",
                        "content": (
                            "-----BEGIN RSA PRIVATE KEY-----\n"
                            "MIIB..."
                        ),
                    }
                ]
            )
        )

    def test_detects_in_tool_messages(self):
        self.assertTrue(
            detect_sensitive(
                [
                    {
                        "role": "tool",
                        "content": "token=abcDEF123456",
                    }
                ]
            )
        )

    def test_plain_text_not_sensitive(self):
        self.assertFalse(
            detect_sensitive(
                [
                    {
                        "role": "user",
                        "content": (
                            "ما سعر البيتكوين اليوم؟ "
                            "الإصدار v2.1 يعمل على 127.0.0.1"
                        ),
                    }
                ]
            )
        )

    def test_version_numbers_not_sensitive(self):
        # Guard against over-gating normal chat.
        self.assertFalse(
            detect_sensitive(
                [
                    {
                        "role": "user",
                        "content": "qwen 4b q4_k_m model test",
                    }
                ]
            )
        )


class TestDualLLMRouting(unittest.TestCase):
    def test_remote_path_delegates_to_hybrid(self):
        local = StubEngine(reply="local-reply")
        hybrid = StubEngine(reply="remote-reply")
        dual = make_dual(local=local, hybrid=hybrid)

        result = dual.chat(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function"}],
        )

        self.assertEqual(
            result["content"], "remote-reply"
        )
        self.assertEqual(len(hybrid.calls), 1)
        self.assertEqual(len(local.calls), 0)

    def test_task_hint_uses_local(self):
        local = StubEngine(reply="local-reply")
        hybrid = StubEngine(reply="remote-reply")
        dual = make_dual(local=local, hybrid=hybrid)

        result = dual.chat(
            [{"role": "user", "content": "summarize this"}],
            task="summarize",
        )

        self.assertEqual(
            result["content"], "local-reply"
        )
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(len(hybrid.calls), 0)

    def test_sensitive_flag_never_touches_remote(self):
        local = StubEngine(reply="local-reply")
        hybrid = StubEngine(reply="remote-reply")
        dual = make_dual(local=local, hybrid=hybrid)

        secret = "sk-abcdefgh12345678"
        result = dual.chat(
            [
                {
                    "role": "user",
                    "content": f"use key {secret}",
                }
            ],
            tools=[{"type": "function"}],
            sensitive=True,
        )

        self.assertEqual(
            result["content"], "local-reply"
        )
        self.assertEqual(len(local.calls), 1)
        # The strong guarantee: remote never saw it.
        self.assertEqual(len(hybrid.calls), 0)
        self.assertNotIn(
            secret, all_texts(hybrid.calls)
        )

    def test_sensitive_auto_detect_never_touches_remote(self):
        local = StubEngine(reply="local-reply")
        hybrid = StubEngine(reply="remote-reply")
        dual = make_dual(local=local, hybrid=hybrid)

        secret = "ghp_1234567890abcdef"
        dual.chat(
            [
                {
                    "role": "user",
                    "content": f"token {secret}",
                }
            ]
        )

        self.assertEqual(len(local.calls), 1)
        self.assertEqual(len(hybrid.calls), 0)
        self.assertNotIn(
            secret, all_texts(hybrid.calls)
        )

    def test_sensitive_local_failure_is_fail_closed(self):
        local = StubEngine(fail=True)
        hybrid = StubEngine(reply="remote-reply")
        dual = make_dual(local=local, hybrid=hybrid)

        result = dual.chat(
            [{"role": "user", "content": "sk-abcdefgh12345678"}],
            sensitive=True,
        )

        self.assertEqual(
            result["content"], FAIL_CLOSED_REFUSAL
        )
        # Fail-closed: no escalation, remote never called.
        self.assertEqual(len(hybrid.calls), 0)

    def test_weak_local_failure_escalates_to_remote(self):
        local = StubEngine(fail=True)
        hybrid = StubEngine(reply="remote-reply")
        dual = make_dual(local=local, hybrid=hybrid)

        result = dual.chat(
            [{"role": "user", "content": "summarize this"}],
            task="summarize",
        )

        # Weak model tried and failed; strong model caught it.
        self.assertEqual(
            result["content"], "remote-reply"
        )
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(len(hybrid.calls), 1)

    def test_audit_records_routing_decision(self):
        events = []

        def audit_fn(event, data):
            events.append((event, data))

        dual = make_dual(audit_fn=audit_fn)
        dual.chat(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function"}],
        )

        routes = [
            e for e in events if e[0] == "llm_route"
        ]
        self.assertEqual(len(routes), 1)
        self.assertEqual(
            routes[0][1]["engine"], "remote"
        )
        # Audit carries the decision, never message content.
        self.assertNotIn("messages", routes[0][1])

    def test_audit_records_escalation(self):
        events = []

        def audit_fn(event, data):
            events.append((event, data))

        dual = make_dual(
            local=StubEngine(fail=True),
            audit_fn=audit_fn,
        )
        dual.chat(
            [{"role": "user", "content": "x"}],
            task="extract",
        )

        names = [e[0] for e in events]
        self.assertIn("llm_route", names)
        self.assertIn("llm_route_escalated", names)

    def test_audit_records_fail_closed(self):
        events = []

        def audit_fn(event, data):
            events.append((event, data))

        dual = make_dual(
            local=StubEngine(fail=True),
            audit_fn=audit_fn,
        )
        dual.chat(
            [{"role": "user", "content": "sk-abcdefgh12345678"}],
            sensitive=True,
        )

        names = [e[0] for e in events]
        self.assertIn("llm_route_fail_closed", names)
        self.assertNotIn("llm_route_escalated", names)

    def test_audit_failure_never_breaks_chat(self):
        def bad_audit(event, data):
            raise RuntimeError("audit down")

        dual = make_dual(audit_fn=bad_audit)
        result = dual.chat(
            [{"role": "user", "content": "hi"}],
            task="format",
        )
        self.assertEqual(
            result["content"], "local-reply"
        )

    def test_status_reports_router(self):
        dual = make_dual()
        info = dual.status()
        self.assertEqual(info["router"], "dual")
        self.assertIn("summarize", info["local_tasks"])


if __name__ == "__main__":
    unittest.main()
