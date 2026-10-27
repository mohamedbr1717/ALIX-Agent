"""Decision 1 (post-E2E fix v4) — telegram router shortcuts.

Root cause #3 of the 2026-10-27 E2E failures, the outermost
one: telegram_bot.route_update() held a pre-Dispatcher Gmail
shortcut that fired on a bare SUBSTRING match — any admin
sentence merely containing one of («بريد», «جميل», "gmail",
"email", «ايميل», «رسائل», "inbox", «صندوق الوارد») was
answered by the router itself with a canned latest-5 dump
(«📧 أحدث الرسائل», query "") and NEVER submitted to the
Dispatcher. No audit, no planning, no agent — while plain
messages («مرحبا», a calendar query) flowed through and
audited normally. Three E2E attempts of the ordered 4-step
task (which ends in «ابحث في Gmail…») all died exactly here,
in front of the two inner causes fixed by v2 and v3.

The contract pinned by this suite: the router transports,
the agent decides. A shortcut may claim ONLY a message that
IS the command — "/gmail", "/gmail <query>" (the remainder
becomes the query), or one bare keyword as the whole
message. Any sentence containing a keyword falls through to
the Dispatcher untouched.
"""
import sys
import types
import unittest
from unittest import mock

#: The exact live task text (pinned in test_planning_intent
#: and test_research_routing_fix as well — the evidence text
#: is repeated on purpose in every layer that must let it
#: through).
TONIGHTS_REQUEST = (
    "نفّذ بالترتيب: أولًا ابحث عن جهة اتصال سعاد، "
    "ثم أنشئ حدثًا في التقويم غدًا على الساعة 10:00 "
    "بعنوان «مكالمة مع سعاد»، ثم احفظ في ذاكرتك رقم هاتف "
    "سعاد الذي وجدته، ثم ابحث في Gmail عن أي رسالة منها"
)

ADMIN_ID = 123456789
UPDATE_ID = 41

_TB_MODULE = None


def _telegram_bot():
    """Import telegram_bot once, with dotenv/openai stubbed
    lazily (same pattern and rationale as
    test_research_routing_fix.py: stubs installed in setUp,
    after discovery, cannot resurrect baseline-error
    modules). telegram_bot imports dotenv_values at module
    level and load_dotenv inside the Gmail handler — the
    stub provides both."""
    global _TB_MODULE
    if _TB_MODULE is None:
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.dotenv_values = lambda *a, **k: {}
        dotenv_stub.load_dotenv = lambda *a, **k: False
        installed_dotenv = sys.modules.setdefault("dotenv", dotenv_stub)
        # Another suite may have installed a dotenv stub
        # first that only carries dotenv_values
        # (test_scheduled_approval installs its shims at
        # module import). telegram_bot's Gmail handler
        # imports load_dotenv at call time — top the
        # installed stub up additively; never replace it.
        if not hasattr(installed_dotenv, "dotenv_values"):
            installed_dotenv.dotenv_values = lambda *a, **k: {}
        if not hasattr(installed_dotenv, "load_dotenv"):
            installed_dotenv.load_dotenv = lambda *a, **k: False

        openai_stub = types.ModuleType("openai")

        class _OpenAIStub:
            def __init__(self, *a, **k):
                raise RuntimeError("openai stub: not usable in tests")

        openai_stub.OpenAI = _OpenAIStub
        installed_openai = sys.modules.setdefault("openai", openai_stub)
        if not hasattr(installed_openai, "OpenAI"):
            installed_openai.OpenAI = _OpenAIStub

        import telegram_bot

        _TB_MODULE = telegram_bot
    return _TB_MODULE


class _FakeAPI:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return len(self.sent)


class _FakeConfirmer:
    pending = False

    def __init__(self):
        self.resolved = []

    def cancel(self):
        return False

    def resolve(self, text):
        self.resolved.append(text)
        return True


class _FakeDispatcher:
    def __init__(self):
        self.submitted = []

    def submit(self, text):
        self.submitted.append(text)


class _FakeGmailController:
    def __init__(self):
        self.calls = []

    def handle(self, dto):
        self.calls.append(dto)
        return {
            "ok": True,
            "messages": [
                {
                    "subject": "رسالة تجريبية",
                    "from": "sender@example.com",
                    "date": "Tue, 27 Oct 2026 10:00",
                    "account": "alix@example.com",
                }
            ],
        }


def _update(text):
    return {
        "update_id": UPDATE_ID,
        "message": {
            "from": {"id": ADMIN_ID},
            "chat": {"id": ADMIN_ID},
            "text": text,
        },
    }


class GmailShortcutRoutingTest(unittest.TestCase):
    """route_update() with recording fakes: the Gmail
    shortcut claims explicit command forms only; every
    sentence mentioning mail reaches the Dispatcher."""

    def setUp(self):
        try:
            self.tb = _telegram_bot()
        except Exception as exc:  # pragma: no cover - env guard
            self.skipTest(f"telegram_bot not importable here: {exc!r}")
        import core.feature_bridge as feature_bridge

        self.api = _FakeAPI()
        self.confirmer = _FakeConfirmer()
        self.dispatcher = _FakeDispatcher()
        self.gmail = _FakeGmailController()
        self.build_calls = []

        def _build():
            self.build_calls.append(True)
            return self.gmail

        patcher = mock.patch.object(
            feature_bridge, "build_gmail_search_controller", _build
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _route(self, text):
        return self.tb.route_update(
            _update(text),
            self.api,
            ADMIN_ID,
            self.confirmer,
            self.dispatcher,
        )

    def _assert_fell_through(self, text):
        offset = self._route(text)
        self.assertEqual(offset, UPDATE_ID + 1)
        self.assertEqual(self.dispatcher.submitted, [text])
        # The router itself answered nothing and never
        # touched the Gmail controller.
        self.assertEqual(self.api.sent, [])
        self.assertEqual(self.build_calls, [])
        self.assertEqual(self.gmail.calls, [])

    def _assert_shortcut(self, text, expected_query):
        offset = self._route(text)
        self.assertEqual(offset, UPDATE_ID + 1)
        self.assertEqual(self.dispatcher.submitted, [])
        self.assertEqual(
            self.gmail.calls,
            [{"query": expected_query, "max_results": 5}],
        )
        self.assertEqual(len(self.api.sent), 1)
        reply = self.api.sent[0][1]
        self.assertTrue(reply.startswith("📧 أحدث الرسائل"), reply)

    # --- the hijack class: sentences must NOT be claimed ---

    def test_tonights_task_falls_through_to_dispatcher(self):
        # The pinned E2E text: an ordered 4-step task whose
        # last step mentions Gmail. The old substring match
        # swallowed it before the agent ever saw it.
        self._assert_fell_through(TONIGHTS_REQUEST)

    def test_gmail_search_sentence_falls_through(self):
        self._assert_fell_through("ابحث في Gmail عن رسالة من سعاد")

    def test_keyword_inside_sentence_falls_through(self):
        # «بريد» inside «بريدي» — a substring, not a command.
        self._assert_fell_through("احفظ أن بريدي مهم")
        # The two-word keyword inside an instruction sentence.
        self.setUp()
        self._assert_fell_through("افتح صندوق الوارد واقرأ آخر رسالة")

    # --- explicit command forms: still claimed ---

    def test_slash_gmail_is_shortcut(self):
        self._assert_shortcut("/gmail", "")

    def test_bare_keyword_is_shortcut(self):
        for text in ("بريد", "gmail"):
            with self.subTest(text=text):
                self.setUp()
                self._assert_shortcut(text, "")

    def test_slash_gmail_with_query_passes_query(self):
        # "/gmail <query>" — the remainder is the search
        # query (previously the shortcut always searched
        # with an empty query).
        self._assert_shortcut("/gmail سعاد", "سعاد")


if __name__ == "__main__":
    unittest.main()
