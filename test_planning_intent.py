"""Decision 1 (post-E2E fix) — the multi-step intent detector.

domain.planning.intent is pure, so these tests need no seams:
they pin the three conservative rules (connectors / enumeration
/ explicit order) against the exact live failure text of
2026-10-27, structural variants, and the near-miss negatives
(single connector, lone greeting opener, dates and times) that
must NOT route a request to the plan path.
"""
import unittest

from domain.planning.intent import (
    is_multi_step_request,
    multi_step_signals,
)

#: The exact request whose live run never created a plan: the
#: model batched its four ordered steps and answered before the
#: old round-3 endurance trigger could fire.
TONIGHTS_REQUEST = (
    "نفّذ بالترتيب: أولًا ابحث عن جهة اتصال سعاد، "
    "ثم أنشئ حدثًا في التقويم غدًا على الساعة 10:00 "
    "بعنوان «مكالمة مع سعاد»، ثم احفظ في ذاكرتك رقم هاتف "
    "سعاد الذي وجدته، ثم ابحث في Gmail عن أي رسالة منها"
)


class TestDetectedRequests(unittest.TestCase):
    def test_tonights_exact_request_is_detected(self):
        self.assertTrue(is_multi_step_request(TONIGHTS_REQUEST))
        signals = multi_step_signals(TONIGHTS_REQUEST)
        self.assertIn("connectors", signals)
        self.assertIn("explicit_order", signals)

    def test_english_ordered_request(self):
        text = (
            "First find Souad's contact, then create a calendar "
            "event for tomorrow, and finally save her number"
        )
        self.assertTrue(is_multi_step_request(text))
        self.assertIn("connectors", multi_step_signals(text))

    def test_two_step_english_with_opener(self):
        text = "First check my calendar, then tell me the result"
        self.assertTrue(is_multi_step_request(text))

    def test_numbered_list_western_digits(self):
        text = (
            "Do the following:\n"
            "1. Search for the contact\n"
            "2. Create the calendar event\n"
            "3. Save the number in memory"
        )
        self.assertTrue(is_multi_step_request(text))
        self.assertIn("enumeration", multi_step_signals(text))

    def test_numbered_list_arabic_indic_digits(self):
        text = "المطلوب:\n١. ابحث عن جهة الاتصال\n٢. أنشئ الحدث\n٣. احفظ الرقم"
        self.assertTrue(is_multi_step_request(text))
        self.assertIn("enumeration", multi_step_signals(text))

    def test_step_labels(self):
        text = "الخطوة 1: افتح الملف، الخطوة 2: اقرأه، الخطوة 3: لخّصه"
        self.assertTrue(is_multi_step_request(text))
        self.assertIn("enumeration", multi_step_signals(text))

    def test_arabic_connector_chain_without_instruction(self):
        text = (
            "أولًا راجع بريدي، ثم لخّص الرسائل المهمة، "
            "وأخيرًا أرسل لي الملخص"
        )
        self.assertTrue(is_multi_step_request(text))
        self.assertIn("connectors", multi_step_signals(text))


class TestRejectedRequests(unittest.TestCase):
    def test_single_step_calendar(self):
        self.assertFalse(is_multi_step_request("اعرض أحداث تقويمي اليوم"))

    def test_single_step_contact_search(self):
        self.assertFalse(is_multi_step_request("ابحث عن جهة اتصال سعاد"))

    def test_plain_question(self):
        self.assertFalse(is_multi_step_request("ما هي عاصمة فرنسا؟"))

    def test_chat_with_a_comma(self):
        self.assertFalse(is_multi_step_request("شكرًا لك، كيف حالك اليوم؟"))

    def test_single_connector_is_not_enough(self):
        # One «ثم» joins two clauses of ONE errand — no chain.
        self.assertFalse(
            is_multi_step_request("ابحث عن سعاد ثم أخبرني برقمها")
        )

    def test_lone_opener_in_greeting(self):
        self.assertFalse(
            is_multi_step_request("أولًا وقبل كل شيء، شكرًا على مساعدتك أمس")
        )

    def test_bare_imperative_without_structure(self):
        self.assertFalse(is_multi_step_request("نفّذ هذه المهمة من فضلك"))

    def test_dates_and_times_are_not_steps(self):
        self.assertFalse(
            is_multi_step_request("موعدنا يوم 27.10 الساعة 10:00 في المكتب")
        )

    def test_empty_and_non_string(self):
        self.assertFalse(is_multi_step_request(""))
        self.assertFalse(is_multi_step_request("   "))
        self.assertFalse(is_multi_step_request(None))
        self.assertEqual(multi_step_signals(None), ())


if __name__ == "__main__":
    unittest.main()
