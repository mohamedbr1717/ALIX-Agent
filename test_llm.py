"""Behavioral tests for core/llm.py — LocalLLM and HybridLLM.

No real network: urllib is mocked for LocalLLM; the OpenAI client is
never constructed (use_remote=False + manual mock injection).
"""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from core.llm import HybridLLM, LocalLLM


def make_urlopen_response(payload: bytes):
    """A context-manager mock mimicking urllib's HTTPResponse."""
    fake = mock.MagicMock()
    fake.read.return_value = payload
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    return fake


def ok_body(content="hi"):
    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": content}}]}
    ).encode()


class TestLocalLLM(unittest.TestCase):
    def make_llm(self):
        return LocalLLM(url="http://127.0.0.1:8081/v1", model="t", timeout=5)

    def test_chat_success(self):
        llm = self.make_llm()
        with mock.patch(
            "urllib.request.urlopen",
            return_value=make_urlopen_response(ok_body("hello")),
        ):
            result = llm.chat([{"role": "user", "content": "hi"}], None)
        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["role"], "assistant")

    def test_chat_no_choices(self):
        llm = self.make_llm()
        with mock.patch(
            "urllib.request.urlopen",
            return_value=make_urlopen_response(b'{"choices": []}'),
        ):
            result = llm.chat([{"role": "user", "content": "hi"}], None)
        self.assertIn("لم يُرجع أي اختيار", result["content"])

    def test_chat_invalid_message(self):
        llm = self.make_llm()
        body = json.dumps({"choices": [{"message": "not-a-dict"}]}).encode()
        with mock.patch(
            "urllib.request.urlopen",
            return_value=make_urlopen_response(body),
        ):
            result = llm.chat([{"role": "user", "content": "hi"}], None)
        self.assertIn("غير صالحة", result["content"])

    def test_chat_http_error(self):
        llm = self.make_llm()
        err = urllib.error.HTTPError(
            url="http://x", code=500, msg="boom",
            hdrs=None, fp=io.BytesIO(b"server blew up"),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = llm.chat([{"role": "user", "content": "hi"}], None)
        self.assertIn("500", result["content"])
        self.assertIn("خطأ HTTP", result["content"])

    def test_chat_url_error(self):
        llm = self.make_llm()
        err = urllib.error.URLError("connection refused")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = llm.chat([{"role": "user", "content": "hi"}], None)
        self.assertIn("تعذر الاتصال", result["content"])

    def test_chat_timeout(self):
        llm = self.make_llm()
        with mock.patch("urllib.request.urlopen",
                         side_effect=TimeoutError()):
            result = llm.chat([{"role": "user", "content": "hi"}], None)
        self.assertIn("انتهت مهلة", result["content"])

    def test_chat_bad_json(self):
        llm = self.make_llm()
        with mock.patch(
            "urllib.request.urlopen",
            return_value=make_urlopen_response(b"not json{{{"),
        ):
            result = llm.chat([{"role": "user", "content": "hi"}], None)
        self.assertIn("JSON غير صالحة", result["content"])

    def test_chat_includes_tools_in_payload(self):
        llm = self.make_llm()
        tools = [{"type": "function",
                  "function": {"name": "system_info"}}]
        with mock.patch(
            "urllib.request.urlopen",
            return_value=make_urlopen_response(ok_body()),
        ) as mock_open:
            llm.chat([{"role": "user", "content": "hi"}], tools)
        request = mock_open.call_args[0][0]
        payload = json.loads(request.data.decode())
        self.assertEqual(payload["tools"], tools)
        self.assertEqual(payload["tool_choice"], "auto")

    def test_chat_never_raises(self):
        # Stability guarantee: every failure mode returns a dict.
        llm = self.make_llm()
        with mock.patch("urllib.request.urlopen",
                         side_effect=RuntimeError("weird")):
            result = llm.chat([], None)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["role"], "assistant")


class TestHybridLLM(unittest.TestCase):
    def make_hybrid(self, **kwargs):
        # use_remote=False: no OpenAI client is ever constructed.
        return HybridLLM(use_remote=False, **kwargs)

    def test_safe_error_redacts_api_key(self):
        h = self.make_hybrid()
        h.api_key = "sk-test-secret-123"
        out = h._safe_error(Exception("boom sk-test-secret-123 end"))
        self.assertNotIn("sk-test-secret-123", out)
        self.assertIn("***REDACTED***", out)

    def test_safe_error_truncates(self):
        h = self.make_hybrid()
        h.api_key = None
        out = h._safe_error(Exception("x" * 5000))
        self.assertLessEqual(len(out), 1000)

    def test_remote_chat_no_client(self):
        h = self.make_hybrid()
        h.client = None
        with self.assertRaises(RuntimeError):
            h._remote_chat([], None)

    def test_remote_chat_success(self):
        h = self.make_hybrid()
        sentinel = object()
        h.client = mock.Mock()
        h.client.chat.completions.create.return_value = sentinel
        self.assertIs(h._remote_chat([{"role": "user"}], None), sentinel)

    def test_remote_chat_retry_without_max_tokens(self):
        h = self.make_hybrid()
        h.client = mock.Mock()
        h.client.chat.completions.create.side_effect = [
            Exception("bad field"), "recovered",
        ]
        result = h._remote_chat([{"role": "user"}], None)
        self.assertEqual(result, "recovered")
        self.assertEqual(h.client.chat.completions.create.call_count, 2)
        second_kwargs = h.client.chat.completions.create.call_args[1]
        self.assertNotIn("max_completion_tokens", second_kwargs)

    def test_chat_remote_success(self):
        h = self.make_hybrid()
        h.use_remote = True
        h.client = mock.Mock()
        fake_response = mock.Mock()
        fake_choice = mock.Mock()
        fake_choice.message = "the-answer"
        fake_response.choices = [fake_choice]
        h._remote_chat = mock.Mock(return_value=fake_response)
        result = h.chat([{"role": "user"}], None)
        self.assertEqual(result, "the-answer")

    def test_chat_retries_then_falls_back_to_local(self):
        h = self.make_hybrid(max_retries=2)
        h.use_remote = True
        h.client = mock.Mock()
        h._remote_chat = mock.Mock(side_effect=Exception("down"))
        h.local.chat = mock.Mock(
            return_value={"role": "assistant", "content": "local"})
        with mock.patch("time.sleep"):
            result = h.chat([{"role": "user"}], None)
        # max_retries + 1 attempts before giving up.
        self.assertEqual(h._remote_chat.call_count, 3)
        h.local.chat.assert_called_once()
        self.assertEqual(result["content"], "local")

    def test_chat_local_only_when_remote_disabled(self):
        h = self.make_hybrid()
        h._remote_chat = mock.Mock(
            side_effect=AssertionError("must not be called"))
        h.local.chat = mock.Mock(
            return_value={"role": "assistant", "content": "local"})
        result = h.chat([{"role": "user"}], None)
        self.assertEqual(result["content"], "local")

    def test_status(self):
        h = self.make_hybrid()
        st = h.status()
        self.assertFalse(st["remote_enabled"])
        self.assertIn("local_url", st)
        self.assertIn("local_model", st)


if __name__ == "__main__":
    unittest.main()
