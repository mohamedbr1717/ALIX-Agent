"""Behavioral tests for the Meta publishing feature slice (phase 1).

Network is fully mocked: no Meta calls, no credentials needed.
Photo fixtures are tiny synthetic byte strings with real magic headers,
created in a temp workspace per test.
"""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from features.meta_publish.application.dto.meta_publish import (
    PostPhotoRequest,
    PostTextRequest,
)
from features.meta_publish.application.use_cases.post_photo import (
    PostPhotoUseCase,
)
from features.meta_publish.application.use_cases.post_text import (
    PostTextUseCase,
)
from features.meta_publish.composition import (
    build_facebook_post_photo_controller,
    build_facebook_post_text_controller,
)
from features.meta_publish.infrastructure.adapters import (
    graph_api_gateway as gw_module,
)
from features.meta_publish.infrastructure.adapters.graph_api_gateway import (
    GraphApiGateway,
)
from features.meta_publish.infrastructure.adapters.policy_meta_authorization import (
    PolicyMetaAuthorizationAdapter,
)
from features.meta_publish.interfaces.controllers.facebook_controllers import (
    FacebookPostPhotoController,
    FacebookPostTextController,
)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class FakePolicy:
    def __init__(self, level, expected=None):
        self._level = level
        self._expected = expected

    def tool_permission(self, name):
        if self._expected is not None:
            assert name == self._expected, name
        else:
            assert name in ("facebook_post_text", "facebook_post_photo"), name
        return self._level


class FakeGateway:
    def __init__(self, result):
        self.result = result
        self.text_calls = []
        self.photo_calls = []

    def post_text(self, message, link=""):
        self.text_calls.append((message, link))
        return self.result

    def post_photo(self, image_path, caption=""):
        self.photo_calls.append((image_path, caption))
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


def make_gateway(root=None, **env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("META_")}
    clean.update(env)
    with patch.dict(os.environ, clean, clear=True):
        return GraphApiGateway(workspace_root=root)


def configured_gateway(root=None, **extra):
    env = {
        "META_PAGE_ID": "860531577134917",
        "META_PAGE_ACCESS_TOKEN": "test-token",
    }
    env.update(extra)
    return make_gateway(root=root, **env)


class TestGatewayConfig(unittest.TestCase):
    def test_missing_page_id_fail_closed(self):
        gw = make_gateway(META_PAGE_ACCESS_TOKEN="tok")
        r = gw.post_text("hello")
        self.assertFalse(r["ok"])
        self.assertIn("META_PAGE_ID", r["error"])

    def test_missing_token_fail_closed(self):
        gw = make_gateway(META_PAGE_ID="123")
        r = gw.post_text("hello")
        self.assertFalse(r["ok"])
        self.assertIn("META_PAGE_ACCESS_TOKEN", r["error"])

    def test_photo_missing_config_fail_closed(self):
        gw = make_gateway()
        r = gw.post_photo("x.jpg")
        self.assertFalse(r["ok"])
        self.assertIn("META_PAGE_ID", r["error"])


class TestPostText(unittest.TestCase):
    def test_empty_message_rejected_before_network(self):
        gw = configured_gateway()
        with patch("urllib.request.urlopen") as m:
            r = gw.post_text("   ")
            self.assertFalse(r["ok"])
            m.assert_not_called()

    def test_too_long_rejected(self):
        gw = configured_gateway()
        r = gw.post_text("x" * 5001)
        self.assertFalse(r["ok"])

    def test_bad_link_scheme_rejected_before_network(self):
        gw = configured_gateway()
        for bad in ("ftp://example.com", "javascript:alert(1)", "example.com"):
            with patch("urllib.request.urlopen") as m:
                r = gw.post_text("hi", link=bad)
                self.assertFalse(r["ok"], bad)
                m.assert_not_called()

    def test_success_returns_post_id(self):
        gw = configured_gateway()
        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse({"id": "860531577134917_42"}),
        ) as m:
            r = gw.post_text("منشور تجريبي", link="https://example.com/x")
            self.assertTrue(r["ok"])
            self.assertEqual(r["post_id"], "860531577134917_42")
            req = m.call_args[0][0]
            self.assertIn("/v26.0/860531577134917/feed", req.full_url)
            sent = json.loads(req.data.decode("utf-8"))
            self.assertEqual(sent["message"], "منشور تجريبي")
            self.assertEqual(sent["link"], "https://example.com/x")
            # token travels in the header only — never URL or body
            self.assertEqual(
                req.headers.get("Authorization"), "Bearer test-token"
            )
            self.assertNotIn("test-token", req.full_url)
            self.assertNotIn("test-token", req.data.decode("utf-8"))

    def test_success_without_link_omits_field(self):
        gw = configured_gateway()
        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse({"id": "p1"}),
        ) as m:
            r = gw.post_text("نص فقط")
            self.assertTrue(r["ok"])
            sent = json.loads(m.call_args[0][0].data.decode("utf-8"))
            self.assertNotIn("link", sent)

    def test_http_error_190_mapped(self):
        gw = configured_gateway()
        body = json.dumps(
            {"error": {"code": 190, "message": "OAuthException"}}
        ).encode()
        err = urllib.error.HTTPError("url", 400, "Bad", {}, io.BytesIO(body))
        with patch("urllib.request.urlopen", side_effect=err):
            r = gw.post_text("hi")
            self.assertFalse(r["ok"])
            self.assertIn("190", r["error"])

    def test_network_failure_fail_closed(self):
        gw = configured_gateway()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        ):
            r = gw.post_text("hi")
            self.assertFalse(r["ok"])

    def test_api_version_overridable(self):
        gw = configured_gateway(META_GRAPH_API_VERSION="v99.0")
        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse({"id": "p"}),
        ) as m:
            gw.post_text("hi")
            self.assertIn("/v99.0/", m.call_args[0][0].full_url)


class TestPostPhoto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "pic.jpg").write_bytes(JPEG_BYTES)
        (self.root / "pic.png").write_bytes(PNG_BYTES)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_rejected_before_network(self):
        gw = configured_gateway(root=self.root)
        with patch("urllib.request.urlopen") as m:
            r = gw.post_photo("nope.jpg")
            self.assertFalse(r["ok"])
            m.assert_not_called()

    def test_path_escape_rejected(self):
        gw = configured_gateway(root=self.root)
        outside = self.root.parent / "outside.jpg"
        outside.write_bytes(JPEG_BYTES)
        try:
            for bad in ("../outside.jpg", str(outside), "/etc/passwd"):
                with patch("urllib.request.urlopen") as m:
                    r = gw.post_photo(bad)
                    self.assertFalse(r["ok"], bad)
                    m.assert_not_called()
        finally:
            outside.unlink(missing_ok=True)

    def test_bad_extension_rejected(self):
        (self.root / "notes.txt").write_bytes(JPEG_BYTES)
        gw = configured_gateway(root=self.root)
        r = gw.post_photo("notes.txt")
        self.assertFalse(r["ok"])

    def test_magic_mismatch_rejected(self):
        (self.root / "fake.jpg").write_bytes(b"this is not a jpeg at all")
        gw = configured_gateway(root=self.root)
        with patch("urllib.request.urlopen") as m:
            r = gw.post_photo("fake.jpg")
            self.assertFalse(r["ok"])
            m.assert_not_called()

    def test_oversize_rejected(self):
        gw = configured_gateway(root=self.root)
        with patch.object(gw_module, "MAX_PHOTO_BYTES", 8):
            r = gw.post_photo("pic.jpg")
            self.assertFalse(r["ok"])

    def test_caption_too_long_rejected(self):
        gw = configured_gateway(root=self.root)
        r = gw.post_photo("pic.jpg", caption="x" * 5001)
        self.assertFalse(r["ok"])

    def test_success_jpeg_multipart(self):
        gw = configured_gateway(root=self.root)
        payload = {"id": "photo123", "post_id": "860531577134917_99"}
        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse(payload),
        ) as m:
            r = gw.post_photo("pic.jpg", caption="تعليق الصورة")
            self.assertTrue(r["ok"])
            self.assertEqual(r["post_id"], "860531577134917_99")
            self.assertEqual(r["photo_id"], "photo123")
            req = m.call_args[0][0]
            self.assertIn("/v26.0/860531577134917/photos", req.full_url)
            self.assertTrue(
                req.headers.get("Content-type", "").startswith(
                    "multipart/form-data; boundary="
                )
            )
            self.assertIn(b'name="source"', req.data)
            self.assertIn(b'filename="pic.jpg"', req.data)
            self.assertIn(JPEG_BYTES, req.data)
            self.assertIn(b'name="caption"', req.data)
            self.assertIn("تعليق الصورة".encode("utf-8"), req.data)
            self.assertNotIn(b"test-token", req.data)
            self.assertNotIn("test-token", req.full_url)

    def test_success_png_without_caption(self):
        gw = configured_gateway(root=self.root)
        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse({"id": "ph", "post_id": "pp"}),
        ) as m:
            r = gw.post_photo("pic.png")
            self.assertTrue(r["ok"])
            self.assertNotIn(b'name="caption"', m.call_args[0][0].data)

    def test_http_error_mapped(self):
        gw = configured_gateway(root=self.root)
        body = json.dumps(
            {"error": {"code": 200, "message": "Permissions error"}}
        ).encode()
        err = urllib.error.HTTPError("url", 403, "No", {}, io.BytesIO(body))
        with patch("urllib.request.urlopen", side_effect=err):
            r = gw.post_photo("pic.jpg")
            self.assertFalse(r["ok"])
            self.assertIn("200", r["error"])


class TestUseCaseAuthorization(unittest.TestCase):
    def test_text_denied_when_level_drifts(self):
        auth = PolicyMetaAuthorizationAdapter(
            FakePolicy("execute", "facebook_post_text"), "facebook_post_text"
        )
        gw = FakeGateway({"ok": True})
        uc = PostTextUseCase(auth, gw)
        r = uc.execute(PostTextRequest(message="hi"))
        self.assertFalse(r["ok"])
        self.assertEqual(gw.text_calls, [])

    def test_text_allowed_when_destructive(self):
        auth = PolicyMetaAuthorizationAdapter(
            FakePolicy("destructive", "facebook_post_text"), "facebook_post_text"
        )
        gw = FakeGateway({"ok": True, "post_id": "p"})
        uc = PostTextUseCase(auth, gw)
        r = uc.execute(PostTextRequest(message="hi", link="https://e.com"))
        self.assertTrue(r["ok"])
        self.assertEqual(gw.text_calls, [("hi", "https://e.com")])

    def test_photo_denied_when_level_drifts(self):
        auth = PolicyMetaAuthorizationAdapter(
            FakePolicy("read", "facebook_post_photo"), "facebook_post_photo"
        )
        gw = FakeGateway({"ok": True})
        uc = PostPhotoUseCase(auth, gw)
        r = uc.execute(PostPhotoRequest(image_path="pic.jpg"))
        self.assertFalse(r["ok"])
        self.assertEqual(gw.photo_calls, [])

    def test_photo_allowed_when_destructive(self):
        auth = PolicyMetaAuthorizationAdapter(
            FakePolicy("destructive", "facebook_post_photo"),
            "facebook_post_photo",
        )
        gw = FakeGateway({"ok": True, "post_id": "p"})
        uc = PostPhotoUseCase(auth, gw)
        r = uc.execute(PostPhotoRequest(image_path="pic.jpg", caption="c"))
        self.assertTrue(r["ok"])
        self.assertEqual(gw.photo_calls, [("pic.jpg", "c")])


class TestControllerAndComposition(unittest.TestCase):
    def test_text_controller_builds_request(self):
        auth = PolicyMetaAuthorizationAdapter(
            FakePolicy("destructive", "facebook_post_text"), "facebook_post_text"
        )
        gw = FakeGateway({"ok": True})
        ctl = FacebookPostTextController(PostTextUseCase(auth, gw))
        r = ctl.handle({"message": "أهلا"})
        self.assertTrue(r["ok"])
        self.assertEqual(gw.text_calls, [("أهلا", "")])

    def test_photo_controller_strips_path(self):
        auth = PolicyMetaAuthorizationAdapter(
            FakePolicy("destructive", "facebook_post_photo"),
            "facebook_post_photo",
        )
        gw = FakeGateway({"ok": True})
        ctl = FacebookPostPhotoController(PostPhotoUseCase(auth, gw))
        r = ctl.handle({"image_path": "  pic.jpg  ", "caption": "x"})
        self.assertTrue(r["ok"])
        self.assertEqual(gw.photo_calls, [("pic.jpg", "x")])

    def test_composition_wires(self):
        policy = FakePolicy("destructive")
        self.assertIsInstance(
            build_facebook_post_text_controller(policy),
            FacebookPostTextController,
        )
        self.assertIsInstance(
            build_facebook_post_photo_controller(policy),
            FacebookPostPhotoController,
        )


if __name__ == "__main__":
    unittest.main()
