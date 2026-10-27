"""Decision 1 (post-E2E fix) — plan-trigger routing in run().

Pins the corrected trigger wiring of core/agent/__init__.py:

* intent-first: a structurally multi-step request is offered
  to _try_plan_escalation BEFORE the ReAct loop (the live E2E
  failure of 2026-10-27: the model batched the task and the
  old round-3 endurance trigger never fired);
* a declined intent attempt falls through to the plain loop;
* the endurance net now fires when ENTERING round 2
  (round_number == 1), not round 3;
* research requests keep precedence over the intent check.

core.agent cannot be imported bare in this environment
(core/llm.py needs python-dotenv and openai, absent here), so
— following test_scheduled_approval.py's shim pattern — the
two modules are stubbed lazily inside setUp, AFTER unittest
discovery has loaded every test module: the stubs therefore
cannot resurrect any module whose import error is part of the
suite baseline. The agent under test is an ALIXAgent shell
(__new__, no __init__) with every collaborator run() touches
replaced by a recording fake; only the routing logic is real.
"""
import io
import sys
import types
import unittest
from contextlib import redirect_stdout

#: Multi-step (connectors + explicit order) with NO research
#: trigger word, so it reaches the intent check.
DETECTED_TEXT = (
    "نفّذ بالترتيب: أولًا أنشئ حدثًا في التقويم غدًا، "
    "ثم احفظ في ذاكرتك أن اختبار الخطة تم، "
    "ثم أرسل لي إشعارًا بالنتيجة"
)

#: Neither detected nor a research request.
PLAIN_TEXT = "نفّذ هذه المهمة من فضلك"

#: A research request that ALSO matches the detector — used to
#: prove the research branch keeps precedence.
RESEARCH_TEXT = "ابحث لي أولًا عن أسعار الذهب، ثم ابحث عن أسعار الفضة"

_AGENT_CLS = None


def _agent_class():
    """Import ALIXAgent once, with dotenv/openai stubbed (see
    module docstring for why the stubs are installed lazily)."""
    global _AGENT_CLS
    if _AGENT_CLS is None:
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.dotenv_values = lambda *a, **k: {}
        sys.modules.setdefault("dotenv", dotenv_stub)

        openai_stub = types.ModuleType("openai")

        class _OpenAIStub:
            def __init__(self, *a, **k):
                raise RuntimeError("openai stub: not usable in tests")

        openai_stub.OpenAI = _OpenAIStub
        sys.modules.setdefault("openai", openai_stub)

        from core.agent import ALIXAgent

        _AGENT_CLS = ALIXAgent
    return _AGENT_CLS


class _FakeLLM:
    """Scripted chat(): pops one canned response per call."""

    def __init__(self, events, script):
        self._events = events
        self._script = list(script)
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        self._events.append("chat")
        return self._script.pop(0)


def _text_response(text):
    return {"text": text}


def _tools_response():
    return {"tool_calls": [("call-1", "noop_tool", {})]}


class PlanTriggerSeamTest(unittest.TestCase):
    def setUp(self):
        try:
            agent_cls = _agent_class()
        except Exception as exc:  # pragma: no cover - env guard
            self.skipTest(f"core.agent not importable here: {exc!r}")
        self.events = []
        self.audits = []
        self.escalation_calls = []
        self.escalation_reply = None
        self.research_calls = []

        agent = agent_cls.__new__(agent_cls)
        agent.observability = types.SimpleNamespace(new_id=lambda: "req-1")
        agent.messages = [{"role": "system", "content": "sys"}]
        agent.memory = types.SimpleNamespace(
            add_history=lambda *a, **k: None
        )
        agent.build_system_message = lambda: "sys"
        agent.audit = lambda event, data=None, **kw: self.audits.append(
            (event, data or {})
        )
        agent._ensure_planning_recovery = lambda: None
        agent._apply_context_boundary = lambda: None
        agent._try_plan_escalation = self._fake_escalation
        agent._run_research = self._fake_research
        agent.extract_tool_calls = (
            lambda resp: resp.get("tool_calls", [])
            if isinstance(resp, dict)
            else []
        )
        agent.message_content = (
            lambda resp: resp.get("text", "")
            if isinstance(resp, dict)
            else ""
        )
        agent.normalize_assistant_message = lambda resp: {
            "role": "assistant",
            "content": "",
        }
        agent.execute_tool = self._fake_execute_tool
        agent._wrap_untrusted_tool_output = (
            lambda name, result: str(result)
        )
        self.agent = agent

    # -- recording fakes -------------------------------------

    def _fake_escalation(self, user_input):
        self.escalation_calls.append(user_input)
        self.events.append("escalation")
        return self.escalation_reply

    def _fake_research(self, user_input):
        self.research_calls.append(user_input)
        return "RESEARCH RESULT"

    def _fake_execute_tool(self, name, arguments):
        self.events.append("tool")
        return "ok"

    # -- helpers ----------------------------------------------

    def _run(self, text, llm_script):
        self.agent.llm = _FakeLLM(self.events, llm_script)
        with redirect_stdout(io.StringIO()):
            return self.agent.run(text)

    def _agent_final_audits(self):
        return [d for (e, d) in self.audits if e == "agent_final"]

    # -- tests -------------------------------------------------

    def test_intent_first_escalation_precedes_any_llm_call(self):
        self.escalation_reply = "PLANNED REPLY"
        result = self._run(DETECTED_TEXT, [_text_response("unused")])
        self.assertEqual(result, "PLANNED REPLY")
        self.assertEqual(self.escalation_calls, [DETECTED_TEXT])
        # The plan answered before the loop: no chat, no tools.
        self.assertEqual(self.events, ["escalation"])
        finals = self._agent_final_audits()
        self.assertEqual(len(finals), 1)
        self.assertTrue(finals[0]["planned"])
        self.assertEqual(finals[0]["round"], 0)

    def test_declined_intent_attempt_falls_back_to_plain_loop(self):
        self.escalation_reply = None
        result = self._run(DETECTED_TEXT, [_text_response("plain answer")])
        self.assertEqual(result, "plain answer")
        self.assertEqual(self.escalation_calls, [DETECTED_TEXT])
        # One pre-loop attempt, then the untouched loop answered
        # in round 1 — no second (endurance) attempt was needed.
        self.assertEqual(self.events, ["escalation", "chat"])

    def test_endurance_escalation_fires_entering_round_two(self):
        self.escalation_reply = None
        result = self._run(
            PLAIN_TEXT, [_tools_response(), _text_response("done")]
        )
        self.assertEqual(result, "done")
        # Round 1 executes a tool; the endurance check runs at
        # the top of round 2 — before its llm call. Under the
        # old round-3 placement this sequence contains NO
        # escalation at all.
        self.assertEqual(
            self.events, ["chat", "tool", "escalation", "chat"]
        )
        self.assertEqual(len(self.escalation_calls), 1)

    def test_endurance_escalation_reply_short_circuits_loop(self):
        self.escalation_reply = "ENDURANCE PLANNED"
        result = self._run(PLAIN_TEXT, [_tools_response()])
        self.assertEqual(result, "ENDURANCE PLANNED")
        self.assertEqual(self.events, ["chat", "tool", "escalation"])
        finals = self._agent_final_audits()
        self.assertEqual(len(finals), 1)
        self.assertTrue(finals[0]["planned"])
        self.assertEqual(finals[0]["round"], 2)

    def test_research_precedence_over_intent(self):
        # Premise: the text really is detector-positive, so only
        # the research branch's precedence keeps it out of plans.
        from domain.planning.intent import is_multi_step_request

        self.assertTrue(is_multi_step_request(RESEARCH_TEXT))
        self.escalation_reply = "SHOULD NOT BE USED"
        result = self._run(RESEARCH_TEXT, [_text_response("unused")])
        self.assertEqual(result, "RESEARCH RESULT")
        self.assertEqual(self.escalation_calls, [])
        self.assertEqual(self.events, [])

    def test_single_step_request_never_escalates(self):
        self.escalation_reply = "SHOULD NOT BE USED"
        result = self._run(
            "اعرض أحداث تقويمي اليوم", [_text_response("لا توجد مواعيد")]
        )
        self.assertEqual(result, "لا توجد مواعيد")
        self.assertEqual(self.escalation_calls, [])
        self.assertEqual(self.events, ["chat"])


if __name__ == "__main__":
    unittest.main()
