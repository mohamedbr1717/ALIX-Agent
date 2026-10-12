"""Behavioral tests for the WhatsApp Cloud API feature slice.

Network is fully mocked: no Meta calls, no credentials needed.
"""
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from features.whatsapp.application.dto.whatsapp import SendWhatsAppRequest
from features.whatsapp.application.use_cases.send_message import (
    SendWhatsAppUseCase,
)
from features.whatsapp.composition import build_whatsapp_send_controller
from features.whatsapp.infrastructure.adapters.cloud_api_gateway import (
    CloudApiGateway,
)
from features.whatsapp.infrastructure.adapters.policy_whatsapp_authorization import (
    PolicyWhatsAppAuthorizationAdapter,
)
from features.whatsapp.interfaces.controllers.whatsapp_controller import (
    SendWhatsAppController,
)


class FakePolicy:
    def __init__(self, level):
        self._level = level

    def tool_permission(self, name):
        assert name == "whatsapp_send"
        return self._level


class FakeGateway:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def send_text(self, to, text):
        self.calls.append((to, text))
        return self.result


class FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_gateway(**env):
    with patch.dict(os.environ, env, clear=False):
        # ensure unrelated env does not leak in
        for k in ("WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
                  "WHATSAPP_API_VERSION"):
            os.environ.pop(k, None)
        with patch.dict(os.environ, env):
            return CloudApiGateway()


class TestNumberNormalization(unittest.TestCase):
    def test_valid_numbers(self):
        self.assertEqual(
            CloudApiGateway.normalize_number("+212 6-23-93-13-32"),
            "212623931332",
        )
        self.assertEqual(
            CloudApiGateway.normalize_number("+1 (555) 667-0012"),
            "15556670012",
        )

    def test_invalid_numbers(self):
        for bad in ["", "abc", "123", "+",
                    "1" * 30, None, 12345]:
            self.assertEqual(CloudApiGateway.normalize_number(bad), "")


class TestGatewayConfig(unittest.TestCase):
    def test_missing_credentials_fail_closed(self):
        gw = make_gateway()
        r = gw.send_text("+212612345678", "hi")
        self.assertFalse(r["ok"])
        self.assertIn("WHATSAPP", r["error"])

    def test_empty_text_rejected(self):
        gw = make_gateway(WHATSAPP_PHONE_NUMBER_ID="123",
                          WHATSAPP_ACCESS_TOKEN="tok")
        r = gw.send_text("+212612345678", "   ")
        self.assertFalse(r["ok"])

    def test_too_long_rejected(self):
        gw = make_gateway(WHATSAPP_PHONE_NUMBER_ID="123",
                          WHATSAPP_ACCESS_TOKEN="tok")
        r = gw.send_text("+212612345678", "x" * 4097)
        self.assertFalse(r["ok"])

    def test_bad_number_rejected_before_network(self):
        gw = make_gateway(WHATSAPP_PHONE_NUMBER_ID="123",
                          WHATSAPP_ACCESS_TOKEN="tok")
        with patch("urllib.request.urlopen") as m:
            r = gw.send_text("not-a-number", "hi")
            self.assertFalse(r["ok"])
            m.assert_not_called()


class TestGatewaySend(unittest.TestCase):
    def _gw(self):
        return make_gateway(WHATSAPP_PHONE_NUMBER_ID="1285338131339159",
                            WHATSAPP_ACCESS_TOKEN="test-token")

    def test_success_returns_message_id(self):
        gw = self._gw()
        payload = {"messages": [{"id": "wamid.abc123"}]}
        with patch("urllib.request.urlopen",
                    return_value=FakeHTTPResponse(payload)) as m:
            r = gw.send_text("+212612345678", "مرحبا")
            self.assertTrue(r["ok"])
            self.assertEqual(r["message_id"], "wamid.abc123")
            req = m.call_args[0][0]
            self.assertIn("1285338131339159/messages", req.full_url)
            self.assertIn("v26.0", req.full_url)
            sent = json.loads(m.call_args[0][0].data.decode("utf-8"))
            self.assertEqual(sent["to"], "212612345678")
            self.assertEqual(sent["messaging_product"], "whatsapp")
            # token must travel in header, never in URL or body
            self.assertNotIn("test-token", req.full_url)
            self.assertNotIn("test-token", json.dumps(sent))

    def test_http_error_mapped(self):
        gw = self._gw()
        body = json.dumps(
            {"error": {"code": 131030, "message": "not allowed"}}).encode()
        err = urllib.error.HTTPError(
            "url", 400, "Bad", {}, io.BytesIO(body))
        with patch("urllib.request.urlopen", side_effect=err):
            r = gw.send_text("+212612345678", "hi")
            self.assertFalse(r["ok"])
            self.assertIn("131030", r["error"])

    def test_network_failure_fail_closed(self):
        gw = self._gw()
        with patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("down")):
            r = gw.send_text("+212612345678", "hi")
            self.assertFalse(r["ok"])

    def test_api_version_overridable(self):
        gw = make_gateway(WHATSAPP_PHONE_NUMBER_ID="1",
                          WHATSAPP_ACCESS_TOKEN="t",
                          WHATSAPP_API_VERSION="v99.0")
        with patch("urllib.request.urlopen",
                    return_value=FakeHTTPResponse(
                        {"messages": [{"id": "x"}]})) as m:
            gw.send_text("+212612345678", "hi")
            self.assertIn("/v99.0/", m.call_args[0][0].full_url)


class TestUseCaseAuthorization(unittest.TestCase):
    def test_denied_when_level_drifts(self):
        auth = PolicyWhatsAppAuthorizationAdapter(FakePolicy("execute"))
        gw = FakeGateway({"ok": True})
        uc = SendWhatsAppUseCase(auth, gw)
        r = uc.execute(SendWhatsAppRequest(to="+2121", text="hi"))
        self.assertFalse(r["ok"])
        self.assertEqual(gw.calls, [])

    def test_allowed_when_destructive(self):
        auth = PolicyWhatsAppAuthorizationAdapter(FakePolicy("destructive"))
        gw = FakeGateway({"ok": True, "message_id": "wamid.x"})
        uc = SendWhatsAppUseCase(auth, gw)
        r = uc.execute(SendWhatsAppRequest(to="+2121", text="hi"))
        self.assertTrue(r["ok"])
        self.assertEqual(len(gw.calls), 1)


class TestControllerAndComposition(unittest.TestCase):
    def test_controller_builds_request(self):
        auth = PolicyWhatsAppAuthorizationAdapter(FakePolicy("destructive"))
        gw = FakeGateway({"ok": True})
        ctl = SendWhatsAppController(SendWhatsAppUseCase(auth, gw))
        r = ctl.handle({"to": " +212612345678 ", "text": "hi"})
        self.assertTrue(r["ok"])
        self.assertEqual(gw.calls[0][0], " +212612345678 ".strip())

    def test_composition_wires(self):
        ctl = build_whatsapp_send_controller(FakePolicy("destructive"))
        self.assertIsInstance(ctl, SendWhatsAppController)


if __name__ == "__main__":
    unittest.main()
