"""Behavioral tests for the interactive browser feature."""
import unittest
from unittest import mock

from features.web.application.dto.browse_page import BrowsePageRequest
from features.web.application.dto.browser_fill import BrowserFillRequest
from features.web.application.dto.browser_submit import BrowserSubmitRequest
from features.web.application.use_cases.browse_page import BrowsePageUseCase
from features.web.application.use_cases.browser_fill import BrowserFillUseCase
from features.web.application.use_cases.browser_submit import BrowserSubmitUseCase
from features.web.infrastructure.adapters.browser_authorization import (
    BrowserAuthorizationAdapter,
)


def make_auth():
    return BrowserAuthorizationAdapter()


def make_runner(**kwargs):
    return mock.Mock(**kwargs)


class TestBrowsePage(unittest.TestCase):
    def test_authorized_url_loads(self):
        runner = make_runner(**{
            "load_page_text.return_value": {"ok": True, "title": "T", "text": "hello"},
        })
        uc = BrowsePageUseCase(make_auth(), runner)
        result = uc.execute(BrowsePageRequest(url="https://example.com"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "browse_page")

    def test_private_ip_rejected(self):
        runner = make_runner()
        uc = BrowsePageUseCase(make_auth(), runner)
        result = uc.execute(BrowsePageRequest(url="http://192.168.1.1/admin"))
        self.assertFalse(result["ok"])
        runner.load_page_text.assert_not_called()

    def test_localhost_rejected(self):
        runner = make_runner()
        uc = BrowsePageUseCase(make_auth(), runner)
        result = uc.execute(BrowsePageRequest(url="http://localhost:8080/"))
        self.assertFalse(result["ok"])

    def test_non_http_rejected(self):
        runner = make_runner()
        uc = BrowsePageUseCase(make_auth(), runner)
        result = uc.execute(BrowsePageRequest(url="file:///etc/passwd"))
        self.assertFalse(result["ok"])


class TestBrowserFill(unittest.TestCase):
    def test_fill_authorized(self):
        runner = make_runner(**{
            "fill_fields.return_value": {"ok": True, "filled": ["#name"]},
        })
        uc = BrowserFillUseCase(make_auth(), runner)
        result = uc.execute(BrowserFillRequest(
            url="https://example.com/form",
            fields={"#name": "Mohamed"},
        ))
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "browser_fill")

    def test_empty_fields_rejected(self):
        runner = make_runner()
        uc = BrowserFillUseCase(make_auth(), runner)
        result = uc.execute(BrowserFillRequest(url="https://example.com", fields={}))
        self.assertFalse(result["ok"])
        runner.fill_fields.assert_not_called()

    def test_unauthorized_url_rejected(self):
        runner = make_runner()
        uc = BrowserFillUseCase(make_auth(), runner)
        result = uc.execute(BrowserFillRequest(
            url="http://10.0.0.1/", fields={"#x": "y"}))
        self.assertFalse(result["ok"])


class TestBrowserSubmit(unittest.TestCase):
    def test_submit_authorized(self):
        runner = make_runner(**{
            "click_submit.return_value": {"ok": True, "result_text": "done"},
        })
        uc = BrowserSubmitUseCase(make_auth(), runner)
        result = uc.execute(BrowserSubmitRequest(
            url="https://example.com/buy",
            selector="#buy-btn",
            description="Buy item",
        ))
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "browser_submit")

    def test_empty_selector_rejected(self):
        runner = make_runner()
        uc = BrowserSubmitUseCase(make_auth(), runner)
        result = uc.execute(BrowserSubmitRequest(url="https://example.com", selector=""))
        self.assertFalse(result["ok"])
        runner.click_submit.assert_not_called()


class TestBrowserPolicyLevels(unittest.TestCase):
    def test_policy_levels(self):
        from core.policy import Policy
        p = Policy()
        self.assertEqual(p.tool_permission("browse_page"), "read")
        self.assertEqual(p.tool_permission("browser_fill"), "execute")
        self.assertEqual(p.tool_permission("browser_submit"), "destructive")

    def test_destructive_never_in_scheduled(self):
        from core.policy import Policy
        p = Policy()
        p.scheduled_mode = True
        p.scheduled_allow = "execute"
        self.assertFalse(p.scheduled_tool_permitted("browser_submit"))
        self.assertTrue(p.scheduled_tool_permitted("browse_page"))


if __name__ == "__main__":
    unittest.main()
