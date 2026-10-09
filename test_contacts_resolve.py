"""Behavioral tests for resolve_contact (contacts feature slice)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from features.contacts.application.dto.resolve_contact import (
    ResolveContactRequest,
)
from features.contacts.application.use_cases.resolve_contact import (
    ResolveContactUseCase,
)
from features.contacts.composition import build_resolve_contact_controller
from features.contacts.domain.contact import normalize_arabic_name
from features.contacts.infrastructure.adapters.json_contacts_repository import (
    JsonContactsRepository,
)


def make_contacts_file(entries) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "contacts.json"
    tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return tmp


FIXTURE = [
    {"name": "أحمد محمد", "number": "+212600000001"},
    {"name": "احمد علي", "number": "+212600000002"},
    {"name": "فاطمة الزهراء", "number": "+212600000003"},
    {"name": "محمد الأمين", "number": "+212600000004"},
]


class TestArabicNormalization(unittest.TestCase):
    def test_hamza_variants_unified(self):
        self.assertEqual(normalize_arabic_name("أحمد"), "احمد")
        self.assertEqual(normalize_arabic_name("إبراهيم"), "ابراهيم")

    def test_diacritics_stripped(self):
        self.assertEqual(normalize_arabic_name("مُحَمَّد"), "محمد")

    def test_ta_marbuta(self):
        self.assertEqual(normalize_arabic_name("فاطمة"), "فاطمه")


class TestResolveContact(unittest.TestCase):
    def setUp(self):
        path = make_contacts_file(FIXTURE)
        self.controller = build_resolve_contact_controller(
            policy=None, contacts_path=path
        )

    def test_exact_match(self):
        r = self.controller.handle({"name": "فاطمة الزهراء"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["number"], "+212600000003")

    def test_normalized_match_finds_hamza_variant(self):
        # query with hamza matches stored name without it
        r = self.controller.handle({"name": "أحمد علي"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["number"], "+212600000002")

    def test_ambiguity_returns_candidates_without_guessing(self):
        r = self.controller.handle({"name": "أحمد"})
        self.assertFalse(r["ok"])
        candidates = r["evidence"]["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertNotIn("number", r)

    def test_no_match(self):
        r = self.controller.handle({"name": "شخص غير موجود"})
        self.assertFalse(r["ok"])
        self.assertNotIn("number", r)

    def test_empty_query_rejected(self):
        r = self.controller.handle({"name": "   "})
        self.assertFalse(r["ok"])

    def test_missing_file_fail_closed(self):
        repo = JsonContactsRepository(path="/nonexistent/contacts.json")
        uc = ResolveContactUseCase(repository=repo)
        r = uc.execute(ResolveContactRequest(name="أحمد"))
        self.assertFalse(r["ok"])

    def test_corrupt_json_fail_closed(self):
        tmp = Path(tempfile.mkdtemp()) / "contacts.json"
        tmp.write_text("{not valid json", encoding="utf-8")
        repo = JsonContactsRepository(path=tmp)
        self.assertEqual(repo.all(), [])

    def test_malformed_entries_skipped(self):
        path = make_contacts_file([
            {"name": "سالم", "number": "+212600000009"},
            {"name": "", "number": "+212600000010"},
            {"name": "بلا رقم"},
            "not a dict",
        ])
        repo = JsonContactsRepository(path=path)
        contacts = repo.all()
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0].name, "سالم")


class TestBridgeWiring(unittest.TestCase):
    def test_handler_registered_in_bridge(self):
        from core.feature_bridge import build_migrated_tool_handlers
        from unittest import mock
        handlers = build_migrated_tool_handlers(
            policy=mock.Mock(), memory=mock.Mock()
        )
        self.assertIn("resolve_contact", handlers)


if __name__ == "__main__":
    unittest.main()
