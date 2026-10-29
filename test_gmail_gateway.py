"""Behavioral tests for GmailGateway.search — ASCII and non-ASCII paths.

Why two paths exist (all verified live against Gmail's IMAP server on
2026-10-29, nine command shapes): Gmail's SEARCH accepts ASCII
criteria only. The original code passed the query as a str and imaplib
ASCII-encoded it, so an Arabic query crashed the tool with
UnicodeEncodeError (plan p_20261028T220418_41cc, step 4). A shipped
UTF-8-charset variant was then rejected by the server itself with
BAD "Could not parse command" — as were 8-bit literals, X-GM-RAW, and
raw 8-bit quoted strings. The gateway therefore keeps server-side TEXT
search for ASCII queries and falls back to a client-side scan of
decoded From/Subject headers for non-ASCII queries.

The fake below emulates the two wire facts that matter: imaplib
ASCII-encodes str arguments (raising on non-ASCII), and Gmail answers
ALL with the full UID list while TEXT answers from a fixed table.
"""

from __future__ import annotations

import base64
import unittest

from features.gmail.gateway import GmailGateway


def _headers(sender: str, subject: str, date: str = "Wed, 29 Oct 2026 09:00:00 +0000") -> bytes:
    return f"From: {sender}\r\nSubject: {subject}\r\nDate: {date}\r\n\r\n".encode("utf-8")


def _encoded_word(text: str) -> str:
    return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


class _FakeIMAP:
    """IMAP double: mailbox of raw headers + a TEXT-search table."""

    def __init__(self, mailbox=None, text_results=None, fail_text_search=False, fail_all_search=False):
        self._mailbox = mailbox or {}
        self._text_results = text_results or {}
        self._fail_text_search = fail_text_search
        self._fail_all_search = fail_all_search
        self.uid_calls = []

    def login(self, address, password):
        return "OK", [b"Logged in"]

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def uid(self, command, *args):
        # imaplib encodes str arguments as ASCII before sending; a
        # non-ASCII str raises UnicodeEncodeError here, exactly as it
        # did in production. Bytes arguments pass as literals.
        for arg in args:
            if isinstance(arg, str):
                arg.encode("ascii")
        self.uid_calls.append((command, args))
        if command == "search":
            return self._search(args)
        if command == "fetch":
            return self._fetch(args)
        return "OK", [b""]

    def _search(self, args):
        if args[-1] == "ALL":
            if self._fail_all_search:
                return "NO", [b""]
            joined = " ".join(sorted(self._mailbox, key=int))
            return "OK", [joined.encode("ascii")]
        if self._fail_text_search:
            self._fail_text_search = False
            return "NO", [b""]
        uids = self._text_results.get(args[-1], [])
        return "OK", [" ".join(uids).encode("ascii")]

    def _fetch(self, args):
        uid_arg = args[0]
        if isinstance(uid_arg, bytes):
            uid_arg = uid_arg.decode("ascii")
        parts = []
        for uid in uid_arg.split(","):
            raw = self._mailbox.get(uid)
            if raw is None:
                continue
            parts.append((f"1 (UID {uid} BODY[HEADER.FIELDS])".encode("ascii"), raw))
            parts.append(b")")
        return "OK", parts

    def logout(self):
        return "BYE", [b""]


def _gateway(fake: _FakeIMAP) -> GmailGateway:
    gateway = GmailGateway(address="user@gmail.com", app_password="abcd efgh")
    gateway._imap = lambda: fake  # noqa: SLF001 - test seam
    return gateway


def _search_calls(fake: _FakeIMAP):
    return [args for command, args in fake.uid_calls if command == "search"]


AR_SUBJECT = "رسالة من سعاد"
MAILBOX = {
    "7": _headers("Souad <souad@example.com>", _encoded_word(AR_SUBJECT)),
    "9": _headers("Shop <shop@example.com>", "Your order has shipped"),
}


class TestGmailSearchAsciiPath(unittest.TestCase):
    def test_ascii_query_uses_server_text_search(self):
        fake = _FakeIMAP(mailbox=MAILBOX, text_results={'"invoice"': ["9"]})
        result = _gateway(fake).search("invoice")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["messages"][0]["uid"], "9")
        self.assertIn((None, "TEXT", '"invoice"'), _search_calls(fake))

    def test_failed_text_search_falls_back_to_all_unfiltered(self):
        fake = _FakeIMAP(mailbox=MAILBOX, fail_text_search=True)
        result = _gateway(fake).search("invoice", limit=1)
        self.assertTrue(result["ok"])
        # Fallback lists the newest message as-is, no local filtering.
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["messages"][0]["uid"], "9")

    def test_empty_query_lists_latest(self):
        fake = _FakeIMAP(mailbox=MAILBOX)
        result = _gateway(fake).search("", limit=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["messages"][0]["uid"], "9")
        self.assertEqual(_search_calls(fake), [(None, "ALL")])


class TestGmailSearchNonAsciiPath(unittest.TestCase):
    def test_arabic_query_matches_subject_via_header_scan(self):
        fake = _FakeIMAP(mailbox=MAILBOX)
        result = _gateway(fake).search("سعاد")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        message = result["messages"][0]
        self.assertEqual(message["uid"], "7")
        self.assertEqual(message["subject"], AR_SUBJECT)
        self.assertIn((None, "ALL"), _search_calls(fake))

    def test_arabic_query_matches_from_name(self):
        mailbox = {
            "4": _headers(f"{_encoded_word('سعاد')} <souad@example.com>", "Hello"),
            "8": _headers("Other <other@example.com>", "Newsletter"),
        }
        fake = _FakeIMAP(mailbox=mailbox)
        result = _gateway(fake).search("سعاد")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["messages"][0]["uid"], "4")

    def test_arabic_query_without_match_returns_empty_ok(self):
        fake = _FakeIMAP(mailbox=MAILBOX)
        result = _gateway(fake).search("خديجة")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["messages"], [])

    def test_arabic_scan_newest_first_and_respects_limit(self):
        mailbox = {
            str(n): _headers("Souad <souad@example.com>", _encoded_word(AR_SUBJECT))
            for n in (5, 6, 7)
        }
        fake = _FakeIMAP(mailbox=mailbox)
        result = _gateway(fake).search("سعاد", limit=2)
        self.assertEqual([m["uid"] for m in result["messages"]], ["7", "6"])

    def test_arabic_scan_finds_match_beyond_first_batch(self):
        mailbox = {
            str(n): _headers("Shop <shop@example.com>", "Offer")
            for n in range(1, 61)
        }
        mailbox["3"] = _headers("Souad <souad@example.com>", _encoded_word(AR_SUBJECT))
        fake = _FakeIMAP(mailbox=mailbox)
        result = _gateway(fake).search("سعاد")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["messages"][0]["uid"], "3")

    def test_arabic_scan_listing_failure_returns_error(self):
        fake = _FakeIMAP(mailbox=MAILBOX, fail_all_search=True)
        result = _gateway(fake).search("سعاد")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


class TestGmailSearchGuards(unittest.TestCase):
    def test_invalid_address_returns_error_not_exception(self):
        gateway = GmailGateway(address="not-an-email", app_password="secret")
        result = gateway.search("سعاد")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
