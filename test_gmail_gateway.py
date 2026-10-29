"""Behavioral tests for GmailGateway.search — non-ASCII (Arabic) queries.

Production failure these tests pin down (plan p_20261028T220418_41cc,
step 4, 2026-10-28): the gateway passed the query to imaplib as a str,
and imaplib ASCII-encodes str criteria, so searching for «سعاد» raised
UnicodeEncodeError ('ascii' codec can't encode characters in position
6-9) and crashed the tool instead of returning a result.

The fake IMAP connection below emulates imaplib faithfully in exactly
that respect: every str argument is ASCII-encoded (raising on
non-ASCII), while bytes arguments pass through as literals. Against
the pre-fix gateway the Arabic tests fail with the production error;
against the fixed gateway (UTF-8 charset + UTF-8 bytes criteria) they
pass.
"""

from __future__ import annotations

import base64
import unittest

from features.gmail.gateway import GmailGateway


class _FakeIMAP:
    """Minimal IMAP double that mimics imaplib's wire encoding."""

    def __init__(self, search_results=None, fetch_payload=b""):
        # (typ, data) tuples consumed in call order, one per search.
        self._search_results = list(search_results or [("OK", [b""])])
        self._fetch_payload = fetch_payload
        self.uid_calls = []

    def login(self, address, password):
        return "OK", [b"Logged in"]

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def uid(self, command, *args):
        # imaplib encodes str arguments as ASCII before sending; a
        # non-ASCII str raises UnicodeEncodeError right here, exactly
        # as it did in production. Bytes are sent as literals.
        for arg in args:
            if isinstance(arg, str):
                arg.encode("ascii")
        self.uid_calls.append((command, args))
        if command == "search":
            if self._search_results:
                return self._search_results.pop(0)
            return "OK", [b""]
        if command == "fetch":
            return "OK", [(b"1 (UID 1)", self._fetch_payload)]
        return "OK", [b""]

    def logout(self):
        return "BYE", [b""]


def _gateway(fake: _FakeIMAP) -> GmailGateway:
    gateway = GmailGateway(address="user@gmail.com", app_password="abcd efgh")
    gateway._imap = lambda: fake  # noqa: SLF001 - test seam
    return gateway


def _search_calls(fake: _FakeIMAP):
    return [args for command, args in fake.uid_calls if command == "search"]


class TestGmailSearchUtf8(unittest.TestCase):
    def test_arabic_query_searches_with_utf8_charset_and_bytes(self):
        fake = _FakeIMAP()
        result = _gateway(fake).search("سعاد")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)
        calls = _search_calls(fake)
        self.assertEqual(len(calls), 1)
        charset, criterion, criteria = calls[0]
        self.assertEqual(charset, "UTF-8")
        self.assertEqual(criterion, "TEXT")
        self.assertEqual(criteria, "سعاد".encode("utf-8"))

    def test_arabic_query_returns_decoded_headers(self):
        subject = "رسالة من سعاد"
        encoded = base64.b64encode(subject.encode("utf-8")).decode("ascii")
        payload = (
            "From: Souad <souad@example.com>\r\n"
            f"Subject: =?UTF-8?B?{encoded}?=\r\n"
            "Date: Wed, 29 Oct 2026 09:00:00 +0000\r\n"
            "\r\n"
        ).encode("ascii")
        fake = _FakeIMAP(search_results=[("OK", [b"7"])], fetch_payload=payload)
        result = _gateway(fake).search("سعاد")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        message = result["messages"][0]
        self.assertEqual(message["uid"], "7")
        self.assertEqual(message["subject"], subject)
        self.assertIn("souad@example.com", message["from"])

    def test_ascii_query_also_uses_utf8_without_quotes(self):
        fake = _FakeIMAP()
        result = _gateway(fake).search("invoice")
        self.assertTrue(result["ok"])
        calls = _search_calls(fake)
        self.assertEqual(calls[0], ("UTF-8", "TEXT", b"invoice"))

    def test_empty_query_searches_all_without_charset(self):
        fake = _FakeIMAP()
        result = _gateway(fake).search("")
        self.assertTrue(result["ok"])
        self.assertEqual(_search_calls(fake), [(None, "ALL")])

    def test_failed_text_search_falls_back_to_all(self):
        fake = _FakeIMAP(search_results=[("NO", [b""]), ("OK", [b""])])
        result = _gateway(fake).search("سعاد")
        self.assertTrue(result["ok"])
        calls = _search_calls(fake)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "UTF-8")
        self.assertEqual(calls[1], (None, "ALL"))

    def test_invalid_address_returns_error_not_exception(self):
        gateway = GmailGateway(address="not-an-email", app_password="secret")
        result = gateway.search("سعاد")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
