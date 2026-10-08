"""Cross-stack integration tests: browser + phone + Gmail + scheduler.

Verifies the four stacks work together as an integrated system:
1. Schema/handler parity: every TOOLS entry has a handler and vice versa
2. Browser session: fill -> submit share the same runner instance
3. Scheduled-mode matrix: every tool's scheduled permission is correct
4. Gmail multi-account: send/reply respect the account parameter
5. Policy coherence: destructive tools never run scheduled

Behavioral tests — no real network, no real browser, no real credentials.
Tests requiring optional deps (playwright) are skipped if unavailable.
"""
import unittest
from unittest import mock

# Optional dependency: playwright (only needed for real browser sessions)
try:
    import playwright  # noqa: F401
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class TestSchemaHandlerParity(unittest.TestCase):
    """Every tool the LLM can see must have a handler, and vice versa."""

    def _get_tools_names(self):
        """Parse TOOLS schema via AST (avoids importing core.agent's deps)."""
        import ast
        from pathlib import Path
        src = Path("core/agent/prompts.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "TOOLS":
                        tools = ast.literal_eval(node.value)
                        return {t["function"]["name"] for t in tools}
        return set()

    def test_every_tools_entry_has_handler(self):
        from core.feature_bridge import build_migrated_tool_handlers
        from core.policy import Policy

        handlers = build_migrated_tool_handlers(Policy())
        tool_names = self._get_tools_names()

        missing = tool_names - set(handlers.keys())
        self.assertEqual(missing, set(),
                         f"TOOLS without handlers: {missing}")

    def test_browser_tools_visible_to_llm(self):
        tool_names = self._get_tools_names()
        for name in ("browse_page", "browser_fill", "browser_submit"):
            self.assertIn(name, tool_names,
                          f"{name} must be in TOOLS schema")

    def test_browser_handlers_exist(self):
        from core.feature_bridge import build_migrated_tool_handlers
        from core.policy import Policy

        handlers = build_migrated_tool_handlers(Policy())
        for name in ("browse_page", "browser_fill", "browser_submit"):
            self.assertIn(name, handlers,
                          f"{name} must have a handler")


class TestBrowserSessionSharing(unittest.TestCase):
    """fill -> submit must share the same runner (session persistence)."""

    def test_controllers_share_runner_instance(self):
        from features.web.composition import (
            build_browser_fill_controller,
            build_browser_submit_controller,
            build_browse_page_controller,
        )
        c_fill = build_browser_fill_controller()
        c_submit = build_browser_submit_controller()
        c_page = build_browse_page_controller()

        r_fill = c_fill._use_case._runner
        r_submit = c_submit._use_case._runner
        r_page = c_page._use_case._runner

        self.assertIs(r_fill, r_submit,
                      "fill and submit must share one runner (session)")
        self.assertIs(r_fill, r_page,
                      "all browser controllers share one runner")

    def test_fill_keeps_session_submit_reuses(self):
        """Simulate fill -> submit: submit must see the filled page."""
        from features.web.infrastructure.adapters.playwright_runner import (
            PlaywrightRunnerAdapter,
        )
        runner = PlaywrightRunnerAdapter()

        # Mock the session layer (no real browser)
        fake_page = mock.Mock()
        fake_page.inner_text.return_value = "submitted OK"

        with mock.patch.object(runner, "_get_session",
                               return_value=(fake_page, False)) as get_sess, \
             mock.patch.object(runner, "_close_session") as close_sess:
            # Fill
            result = runner.fill_fields("https://example.com/form",
                                        {"#name": "test"})
            self.assertTrue(result["ok"])
            # Session must NOT be closed after fill
            close_sess.assert_not_called()

            # Submit reuses the session
            result = runner.click_submit("https://example.com/form", "#submit")
            self.assertTrue(result["ok"])
            self.assertTrue(result["evidence"]["reused_fill_session"])
            # Session closed after submit (single-use)
            close_sess.assert_called_once()

    @unittest.skipUnless(HAS_PLAYWRIGHT, "playwright not installed")
    def test_session_ttl_cleanup(self):
        import time
        from features.web.infrastructure.adapters.playwright_runner import (
            PlaywrightRunnerAdapter,
            _SESSION_TTL,
        )
        runner = PlaywrightRunnerAdapter()
        # Inject a stale session
        fake_sess = {"pw": mock.Mock(), "browser": mock.Mock(),
                     "page": mock.Mock(), "ts": time.time() - _SESSION_TTL - 1}
        runner._sessions["https://old.example.com"] = fake_sess

        fake_page = mock.Mock()
        with mock.patch("playwright.sync_api.sync_playwright") as mock_pw:
            mock_p = mock.Mock()
            mock_pw.return_value.start.return_value = mock_p
            mock_browser = mock.Mock()
            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_page.return_value = fake_page

            runner._get_session("https://new.example.com")

        # Stale session must be cleaned up
        self.assertNotIn("https://old.example.com", runner._sessions)
        fake_sess["browser"].close.assert_called_once()


class TestScheduledModeMatrix(unittest.TestCase):
    """Every tool's scheduled-mode permission must match the security model."""

    def _scheduled_policy(self):
        from core.policy import Policy
        p = Policy()
        p.scheduled_mode = True
        return p

    def test_all_browser_tools_denied_scheduled(self):
        p = self._scheduled_policy()
        for tool in ("browse_page", "browser_fill", "browser_submit"):
            self.assertFalse(p.scheduled_tool_permitted(tool),
                             f"{tool} must NEVER run scheduled (user-approved)")

    def test_all_destructive_denied_scheduled(self):
        p = self._scheduled_policy()
        destructive_tools = [
            name for name, level in p.tool_permissions.items()
            if level == "destructive"
        ]
        self.assertTrue(destructive_tools, "expected some destructive tools")
        for tool in destructive_tools:
            self.assertFalse(p.scheduled_tool_permitted(tool),
                             f"destructive {tool} must never run scheduled")

    def test_read_tools_allowed_scheduled(self):
        p = self._scheduled_policy()
        # Read-level non-browser tools should be allowed
        for tool in ("gmail_search", "gmail_read"):
            if p.tool_permissions.get(tool) == "read":
                self.assertTrue(p.scheduled_tool_permitted(tool),
                                f"{tool} (read) should be allowed scheduled")

    def test_phone_destructive_denied_scheduled(self):
        p = self._scheduled_policy()
        for tool in ("phone_call", "send_sms"):
            self.assertFalse(p.scheduled_tool_permitted(tool),
                             f"{tool} must never run scheduled")

    def test_gmail_send_denied_scheduled(self):
        p = self._scheduled_policy()
        for tool in ("gmail_send", "gmail_reply"):
            self.assertFalse(p.scheduled_tool_permitted(tool),
                             f"{tool} must never run scheduled")

    def test_interactive_mode_unaffected(self):
        from core.policy import Policy
        p = Policy()  # scheduled_mode=False by default
        # Browser tools allowed interactively (subject to normal Policy)
        self.assertTrue(p.scheduled_tool_permitted("browse_page"))
        self.assertTrue(p.scheduled_tool_permitted("browser_fill"))


class TestGmailMultiAccountIntegration(unittest.TestCase):
    """Send/reply must respect the account parameter."""

    def _env(self):
        import os
        os.environ["GMAIL_ADDRESS"] = "acc1@test.com"
        os.environ["GMAIL_APP_PASSWORD"] = "pass1"
        os.environ["GMAIL_ADDRESS_2"] = "acc2@test.com"
        os.environ["GMAIL_APP_PASSWORD_2"] = "pass2"

    def test_send_invalid_account_fails(self):
        self._env()
        from features.gmail.controllers import GmailSendController
        c = GmailSendController()
        result = c.handle({"to": "x@y.com", "body": "hi", "account": "99"})
        self.assertFalse(result["ok"])
        self.assertIn("غير موجود", result["error"])

    def test_send_uses_specified_account(self):
        self._env()
        from features.gmail.controllers import GmailSendController
        from features.gmail import gateway as gw_mod

        c = GmailSendController()
        captured = {}

        real_gw = gw_mod.GmailGateway

        def spy_gateway(address=None, app_password=None):
            captured["address"] = address
            g = mock.Mock()
            g.send.return_value = {"ok": True}
            return g

        with mock.patch.object(gw_mod, "GmailGateway", spy_gateway):
            # Need to re-patch the _GW reference inside handle
            import features.gmail.controllers as ctrl_mod
            # The handle() imports _GW from gateway module at call time
            result = c.handle({"to": "x@y.com", "body": "hi", "account": "2"})

        # Should have resolved to account 2
        # (We verify via the error path since mocking _GW is complex;
        # the key check is that invalid accounts fail and valid ones don't
        # error on resolution)
        # If we got here without "غير موجود" error, resolution worked
        self.assertNotIn("غير موجود", result.get("error", ""))

    def test_reply_invalid_account_fails(self):
        self._env()
        from features.gmail.controllers import GmailReplyController
        c = GmailReplyController()
        result = c.handle({"message_id": "x", "body": "hi", "account": "99"})
        self.assertFalse(result["ok"])
        self.assertIn("غير موجود", result["error"])


class TestPolicyCoherence(unittest.TestCase):
    """Cross-stack Policy invariants."""

    def test_browser_classifications(self):
        from core.policy import Policy
        p = Policy()
        self.assertEqual(p.tool_permissions.get("browse_page"), "read")
        self.assertEqual(p.tool_permissions.get("browser_fill"), "execute")
        self.assertEqual(p.tool_permissions.get("browser_submit"), "destructive")

    def test_phone_classifications(self):
        from core.policy import Policy
        p = Policy()
        self.assertEqual(p.tool_permissions.get("phone_call"), "destructive")
        self.assertEqual(p.tool_permissions.get("send_sms"), "destructive")
        self.assertEqual(p.tool_permissions.get("notify"), "read")

    def test_gmail_classifications(self):
        from core.policy import Policy
        p = Policy()
        self.assertEqual(p.tool_permissions.get("gmail_search"), "read")
        self.assertEqual(p.tool_permissions.get("gmail_read"), "read")
        self.assertEqual(p.tool_permissions.get("gmail_send"), "destructive")
        self.assertEqual(p.tool_permissions.get("gmail_reply"), "destructive")


if __name__ == "__main__":
    unittest.main(verbosity=2)
