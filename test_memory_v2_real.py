import json
import tempfile
import unittest
from pathlib import Path

from core.memory import Memory


class TestMemoryV2Real(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "memory.json"
        self.memory = Memory(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_initial_structure_is_valid(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))

        self.assertEqual(data["version"], 2)
        self.assertEqual(data["facts"], [])
        self.assertEqual(data["preferences"], [])
        self.assertEqual(data["history"], [])

    def test_fact_is_persisted_and_duplicates_are_rejected(self):
        self.assertTrue(self.memory.add_fact("ALIX uses secure tools"))
        self.assertTrue(self.memory.add_fact("ALIX uses secure tools"))

        data = self.memory.get_context()

        self.assertEqual(len(data["facts"]), 1)
        self.assertEqual(data["facts"][0]["text"], "ALIX uses secure tools")

        # تحقق فعلي من persistence عبر إنشاء instance جديدة.
        second = Memory(self.path)
        self.assertEqual(
            second.get_context()["facts"][0]["text"],
            "ALIX uses secure tools",
        )

    def test_preference_is_persisted_and_duplicates_are_rejected(self):
        self.assertTrue(self.memory.add_preference("Arabic responses"))

        self.assertTrue(self.memory.add_preference("Arabic responses"))

        data = self.memory.get_context()

        self.assertEqual(len(data["preferences"]), 1)
        self.assertEqual(
            data["preferences"][0]["text"],
            "Arabic responses",
        )

    def test_history_is_persisted_and_invalid_entries_are_rejected(self):
        self.assertTrue(
            self.memory.add_history(
                "user",
                "اختبر الذاكرة",
            )
        )

        self.assertFalse(self.memory.add_history("", "content"))
        self.assertFalse(self.memory.add_history("user", ""))

        history = self.memory.get_context()["history"]

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "اختبر الذاكرة")

    def test_text_is_sanitized_and_bounded(self):
        long_text = "A" * (Memory.MAX_TEXT_LENGTH + 500)

        self.assertTrue(self.memory.add_fact(long_text))

        stored = self.memory.get_context()["facts"][0]["text"]

        self.assertEqual(len(stored), Memory.MAX_TEXT_LENGTH)
        self.assertNotIn("\x00", stored)

    def test_search_finds_facts_and_preferences(self):
        self.memory.add_fact("OpenRouter model")
        self.memory.add_preference("Arabic language")

        results = self.memory.search("openrouter")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "facts")
        self.assertEqual(results[0]["text"], "OpenRouter model")

        results = self.memory.search("ARABIC")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "preferences")

    def test_search_limit_is_enforced(self):
        for index in range(5):
            self.memory.add_fact(f"security test {index}")

        results = self.memory.search("security", limit=2)

        self.assertEqual(len(results), 2)

    def test_clear_history_does_not_delete_facts(self):
        self.memory.add_fact("Important fact")
        self.memory.add_history("user", "Old message")

        self.assertTrue(self.memory.clear_history())

        context = self.memory.get_context()

        self.assertEqual(len(context["history"]), 0)
        self.assertEqual(len(context["facts"]), 1)

    def test_clear_all_resets_memory(self):
        self.memory.add_fact("Fact")
        self.memory.add_preference("Preference")
        self.memory.add_history("user", "History")

        self.assertTrue(self.memory.clear_all())

        context = self.memory.get_context()

        self.assertEqual(context["facts"], [])
        self.assertEqual(context["preferences"], [])
        self.assertEqual(context["history"], [])

    def test_corrupted_primary_recovers_from_backup(self):
        # إنشاء أول نسخة من الذاكرة.
        self.assertTrue(
            self.memory.add_fact("Recovery fact")
        )

        # إضافة عنصر ثانٍ لإنشاء backup يحتوي على النسخة السابقة.
        self.assertTrue(
            self.memory.add_fact("Second fact")
        )

        backup = self.memory.backup_path
        self.assertTrue(backup.exists())

        # تحقق فعلي من محتوى الـ backup قبل إفساد primary.
        backup_data = json.loads(
            backup.read_text(encoding="utf-8")
        )

        backup_facts = [
            item.get("text")
            for item in backup_data["facts"]
            if isinstance(item, dict)
        ]

        self.assertIn(
            "Recovery fact",
            backup_facts,
        )

        self.assertNotIn(
            "Second fact",
            backup_facts,
        )

        # إفساد الملف الأساسي عمدًا.
        self.path.write_text(
            "{ this is invalid json",
            encoding="utf-8",
        )

        # إعادة إنشاء Memory يجب أن تستعيد بيانات الـ backup.
        recovered = Memory(self.path)
        context = recovered.get_context()

        recovered_facts = [
            item.get("text")
            for item in context["facts"]
            if isinstance(item, dict)
        ]

        # هذا هو الـ behavioral assertion الحقيقي.
        self.assertIn(
            "Recovery fact",
            recovered_facts,
        )

        # العنصر الثاني لم يكن موجودًا في الـ backup،
        # لذلك لا يجب أن يظهر بعد recovery.
        self.assertNotIn(
            "Second fact",
            recovered_facts,
        )

    def test_normalize_repairs_invalid_collections(self):
        data = {
            "facts": "invalid",
            "preferences": None,
            "history": {"invalid": True},
        }

        normalized = self.memory._normalize(data)

        self.assertEqual(normalized["version"], 2)
        self.assertEqual(normalized["facts"], [])
        self.assertEqual(normalized["preferences"], [])
        self.assertEqual(normalized["history"], [])

    def test_stats_matches_actual_memory(self):
        self.memory.add_fact("Fact 1")
        self.memory.add_fact("Fact 2")
        self.memory.add_preference("Preference")
        self.memory.add_history("user", "Message")

        stats = self.memory.stats()

        self.assertEqual(stats["facts"], 2)
        self.assertEqual(stats["preferences"], 1)
        self.assertEqual(stats["history"], 1)


    def test_backup_remains_intact_after_recovery(self):
        self.assertTrue(
            self.memory.add_fact("Recovery fact")
        )

        self.assertTrue(
            self.memory.add_fact("Second fact")
        )

        backup = self.memory.backup_path
        self.assertTrue(backup.exists())

        backup_before = backup.read_text(
            encoding="utf-8"
        )

        self.path.write_text(
            "{ corrupted primary",
            encoding="utf-8",
        )

        recovered = Memory(self.path)

        self.assertEqual(
            backup.read_text(
                encoding="utf-8"
            ),
            backup_before,
        )

        context = recovered.get_context()

        recovered_facts = [
            item.get("text")
            for item in context["facts"]
            if isinstance(item, dict)
        ]

        self.assertIn(
            "Recovery fact",
            recovered_facts,
        )

        self.assertNotIn(
            "Second fact",
            recovered_facts,
        )



class TestMemoryV2FailureAndLimits(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "memory.json"
        self.memory = Memory(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_corrupted_json_load_fails_closed(self):
        self.path.write_text(
            "{ definitely not valid json",
            encoding="utf-8",
        )

        loaded = self.memory._load()

        self.assertEqual(
            loaded,
            {
                "version": 2,
                "facts": [],
                "preferences": [],
                "history": [],
            },
        )

    def test_invalid_structure_load_fails_closed(self):
        self.path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "facts": "not-a-list",
                    "preferences": [],
                    "history": [],
                }
            ),
            encoding="utf-8",
        )

        loaded = self.memory._load()

        self.assertEqual(loaded["facts"], [])
        self.assertEqual(loaded["preferences"], [])
        self.assertEqual(loaded["history"], [])

    def test_restore_backup_without_backup_fails_cleanly(self):
        self.assertFalse(self.memory.backup_path.exists())

        self.assertFalse(
            self.memory._restore_backup()
        )

    def test_invalid_backup_is_rejected(self):
        self.memory.backup_path.write_text(
            "{ invalid backup",
            encoding="utf-8",
        )

        self.assertFalse(
            self.memory._restore_backup()
        )

    def test_save_failure_does_not_report_success(self):
        original_path = self.memory.path

        # اجعل المسار هدفًا غير قابل للاستبدال كملف.
        blocked_dir = Path(self.tmp.name) / "blocked"
        blocked_dir.mkdir()

        self.memory.path = blocked_dir / "memory.json"

        # نمنع os.replace فقط، ونختبر عقدة _save نفسها.
        from unittest.mock import patch

        try:
            with patch(
                "core.memory.os.replace",
                side_effect=OSError("forced replace failure"),
            ):
                result = self.memory._save(
                    self.memory._empty_memory()
                )
        finally:
            self.memory.path = original_path

        self.assertFalse(result)

    def test_fact_limit_is_enforced(self):
        for index in range(
            self.memory.MAX_FACTS + 25
        ):
            self.assertTrue(
                self.memory.add_fact(
                    f"fact-{index}"
                )
            )

        facts = self.memory.get_context()["facts"]

        self.assertEqual(
            len(facts),
            self.memory.MAX_FACTS,
        )

        self.assertEqual(
            facts[0]["text"],
            f"fact-25",
        )

        self.assertEqual(
            facts[-1]["text"],
            f"fact-{self.memory.MAX_FACTS + 24}",
        )

    def test_preference_limit_is_enforced(self):
        for index in range(
            self.memory.MAX_PREFERENCES + 10
        ):
            self.assertTrue(
                self.memory.add_preference(
                    f"preference-{index}"
                )
            )

        preferences = self.memory.get_context()["preferences"]

        self.assertEqual(
            len(preferences),
            self.memory.MAX_PREFERENCES,
        )

        self.assertEqual(
            preferences[0]["text"],
            "preference-10",
        )

    def test_history_limit_is_enforced(self):
        for index in range(
            self.memory.MAX_HISTORY + 10
        ):
            self.assertTrue(
                self.memory.add_history(
                    "user",
                    f"message-{index}",
                )
            )

        history = self.memory.get_context()["history"]

        self.assertEqual(
            len(history),
            self.memory.MAX_HISTORY,
        )

        self.assertEqual(
            history[0]["content"],
            "message-10",
        )

    def test_legacy_string_entries_are_still_detected_as_duplicates(self):
        data = self.memory._empty_memory()
        data["facts"] = ["legacy fact"]

        self.path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.assertTrue(
            self.memory.add_fact("legacy fact")
        )

        self.assertEqual(
            self.memory.get_context()["facts"],
            ["legacy fact"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
