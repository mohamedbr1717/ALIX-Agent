"""Decision 1 (post-E2E fix v3) — research-hijack regression.

Pins the three-part v3 fix in core/agent/__init__.py, built on
the live headless reproduction of 2026-10-27 21:49: run() with
the ordered 4-step Arabic task (TONIGHTS_REQUEST) returned a
RESEARCH-mode answer — because

1. run() checked _is_research_request BEFORE the v2 intent
   check, and
2. _RESEARCH_TRIGGERS contained the bare substring «ابحث»,
   which the task carries twice («ابحث عن جهة اتصال»,
   «ابحث في Gmail») — ordinary action commands, not research;
3. worse, the research planner LLM's refusal line became a
   sub-question, was web-searched, and the distiller returned
   a dictionary definition of "I'm sorry, but I can't help
   with that" formatted as a fact — refusal text must never
   become a search query.

The suite is split in three:
* classification (pure predicates on an agent shell): the
  hijack class is dead, genuine research phrasings survive;
* run() seam routing (the v2 harness pattern — lazy
  dotenv/openai stubs in setUp, __new__ shell, recording
  fakes): intent is attempted BEFORE research, and a genuine
  research request still reaches research;
* the REAL _run_research with faked LLM/tools: planner
  refusal lines are dropped before searching, and a
  refusal-only planner output yields the ⚠️ fallback.
"""
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

from domain.planning.intent import is_multi_step_request

#: The exact live task text (same fixture as
#: test_planning_intent.TONIGHTS_REQUEST — the evidence text
#: is pinned in both places on purpose).
TONIGHTS_REQUEST = (
    "نفّذ بالترتيب: أولًا ابحث عن جهة اتصال سعاد، "
    "ثم أنشئ حدثًا في التقويم غدًا على الساعة 10:00 "
    "بعنوان «مكالمة مع سعاد»، ثم احفظ في ذاكرتك رقم هاتف "
    "سعاد الذي وجدته، ثم ابحث في Gmail عن أي رسالة منها"
)

#: Detector-positive AND a genuine research phrasing — the
#: adversarial mixed text the v2 precedence test lacked (its
#: fixture used this shape too, but asserted the old order).
RESEARCH_TEXT = "ابحث لي أولًا عن أسعار الذهب، ثم ابحث عن أسعار الفضة"

#: A genuine research request that is NOT multi-step.
RESEARCH_SINGLE = "ابحث لي عن أسعار الذهب اليوم"

_AGENT_CLS = None


def _agent_class():
    """Import ALIXAgent once, with dotenv/openai stubbed
    lazily (same pattern and rationale as
    test_planning_trigger.py: stubs installed in setUp,
    after discovery, cannot resurrect baseline-error
    modules)."""
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


class ResearchClassificationTest(unittest.TestCase):
    """_is_research_request / is_multi_step_request on the
    bare agent shell (the predicate uses class attributes
    only)."""

    def setUp(self):
        try:
            agent_cls = _agent_class()
        except Exception as exc:  # pragma: no cover - env guard
            self.skipTest(f"core.agent not importable here: {exc!r}")
        self.shell = agent_cls.__new__(agent_cls)

    def _is_research(self, text):
        return self.shell._is_research_request(text)

    def test_tonights_request_is_not_research_but_is_multi_step(self):
        # The pinned hijack: «ابحث» appears twice in an
        # ordered ACTION task. It must classify as a
        # multi-step action — never as web research.
        self.assertFalse(self._is_research(TONIGHTS_REQUEST))
        self.assertTrue(is_multi_step_request(TONIGHTS_REQUEST))

    def test_bare_search_action_commands_are_not_research(self):
        for text in (
            "ابحث عن جهة اتصال سعاد",
            "ابحث في Gmail عن رسالة من سعاد",
            "ابحث في الملفات عن تقرير الميزانية",
        ):
            with self.subTest(text=text):
                self.assertFalse(self._is_research(text))

    def test_genuine_research_phrasings_still_classify(self):
        # Every phrasing the pre-v3 suite/fixtures rely on,
        # kept working after the bare «ابحث» was removed.
        for text in (
            RESEARCH_TEXT,                       # «ابحث لي»
            RESEARCH_SINGLE,                     # «ابحث لي»
            "اجمع لي بيانات عن أسعار النفط",      # «اجمع لي بيانات»
            "تجمع لي بيانات حول سوق الأسهم",     # «تجمع لي بيانات»
            "اجمع بيانات عن تغيّر المناخ",        # «اجمع بيانات»
            "research the latest AI models",     # "research"
        ):
            with self.subTest(text=text):
                self.assertTrue(self._is_research(text))


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


class ResearchRoutingSeamTest(unittest.TestCase):
    """run() routing with recording fakes (v2 harness style):
    intent is attempted BEFORE research; research is still
    reached by genuine phrasings."""

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
        agent.execute_tool = lambda name, arguments: "ok"
        agent._wrap_untrusted_tool_output = (
            lambda name, result: str(result)
        )
        self.agent = agent

    def _fake_escalation(self, user_input):
        self.escalation_calls.append(user_input)
        self.events.append("escalation")
        return self.escalation_reply

    def _fake_research(self, user_input):
        self.research_calls.append(user_input)
        return "RESEARCH RESULT"

    def _run(self, text, llm_script):
        self.agent.llm = _FakeLLM(self.events, llm_script)
        with redirect_stdout(io.StringIO()):
            return self.agent.run(text)

    def test_tonights_request_escalates_and_never_enters_research(self):
        self.escalation_reply = "PLANNED REPLY"
        result = self._run(TONIGHTS_REQUEST, [{"text": "unused"}])
        self.assertEqual(result, "PLANNED REPLY")
        self.assertEqual(self.escalation_calls, [TONIGHTS_REQUEST])
        self.assertEqual(self.research_calls, [])
        self.assertEqual(self.events, ["escalation"])

    def test_research_text_attempted_first_then_research_on_decline(self):
        # Adversarial mixed text: detector-positive AND a
        # genuine research phrasing. v3 order offers it to
        # the planner first; on decline it must STILL reach
        # research (the v2 test asserted research-first and
        # missed the hijack precisely here).
        self.escalation_reply = None
        result = self._run(RESEARCH_TEXT, [{"text": "unused"}])
        self.assertEqual(result, "RESEARCH RESULT")
        self.assertEqual(self.escalation_calls, [RESEARCH_TEXT])
        self.assertEqual(self.research_calls, [RESEARCH_TEXT])

    def test_single_step_research_skips_intent_entirely(self):
        self.assertFalse(is_multi_step_request(RESEARCH_SINGLE))
        self.escalation_reply = "SHOULD NOT BE USED"
        result = self._run(RESEARCH_SINGLE, [{"text": "unused"}])
        self.assertEqual(result, "RESEARCH RESULT")
        self.assertEqual(self.escalation_calls, [])
        self.assertEqual(self.research_calls, [RESEARCH_SINGLE])


class ResearchPlannerRefusalTest(unittest.TestCase):
    """The REAL _run_research, with the LLM and tools faked:
    planner refusal lines are filtered before any search."""

    INSUFFICIENT = (
        "⚠️ تعذّرت جمع بيانات بحث كافية لهذا الطلب. "
        "حاول صياغة أضيق أو أعد المحاولة بعد قليل."
    )

    def setUp(self):
        try:
            agent_cls = _agent_class()
        except Exception as exc:  # pragma: no cover - env guard
            self.skipTest(f"core.agent not importable here: {exc!r}")
        self.audits = []
        self.searched_queries = []
        self.planner_output = ""

        agent = agent_cls.__new__(agent_cls)
        agent.messages = [{"role": "system", "content": "sys"}]
        agent.memory = types.SimpleNamespace(
            add_history=lambda *a, **k: None
        )
        agent.audit = lambda event, data=None, **kw: self.audits.append(
            (event, data or {})
        )
        agent._research_llm_text = self._fake_research_llm_text
        agent.execute_tool = self._fake_execute_tool
        agent._wrap_untrusted_tool_output = (
            lambda name, result: str(result)
        )
        self.agent = agent

    def _fake_research_llm_text(self, messages):
        system = messages[0]["content"]
        if "مخطط بحث" in system:  # the research planner
            return self.planner_output
        if "مقطّر" in system:  # the distiller
            return "حقيقة تجريبية | مصدر تجريبي | ملاحظة تجريبية"
        return "إجابة مركّبة"  # the synthesizer

    def _fake_execute_tool(self, name, arguments):
        if name == "web_search":
            self.searched_queries.append(arguments["query"])
            return "نتائج بحث تجريبية بلا روابط"
        raise AssertionError(f"unexpected tool call: {name}")

    def _run_research(self, text="ابحث لي عن أسعار الذهب"):
        with mock.patch("time.sleep", lambda *a, **k: None):
            return self.agent._run_research(text)

    def _final_audit(self):
        finals = [d for (e, d) in self.audits if e == "agent_final"]
        self.assertEqual(len(finals), 1)
        return finals[0]

    def test_refusal_lines_never_become_search_queries(self):
        # The live degeneration, replayed: the planner mixes
        # refusal lines (Arabic + English markers) with one
        # genuine sub-question. Only the question is searched.
        self.planner_output = (
            "لا أستطيع المساعدة في هذا الطلب\n"
            "I'm sorry, but I can't help with that.\n"
            "ما هي أسعار الذهب اليوم؟"
        )
        result = self._run_research()
        self.assertEqual(self.searched_queries, ["ما هي أسعار الذهب اليوم؟"])
        self.assertEqual(result, "إجابة مركّبة")
        self.assertEqual(self._final_audit()["parts"], 1)

    def test_refusal_only_planner_output_yields_insufficient_data(self):
        # The exact 2026-10-27 21:49 planner behavior: its
        # whole output is a refusal. Nothing may be searched;
        # the ⚠️ insufficient-data answer is the outcome —
        # NOT a web search for the refusal sentence (which
        # produced the Ludwig dictionary definition live).
        self.planner_output = "I'm sorry, but I can't help with that."
        result = self._run_research()
        self.assertEqual(self.searched_queries, [])
        self.assertEqual(result, self.INSUFFICIENT)
        final = self._final_audit()
        self.assertTrue(final["research"])
        self.assertEqual(final["parts"], 0)


if __name__ == "__main__":
    unittest.main()
