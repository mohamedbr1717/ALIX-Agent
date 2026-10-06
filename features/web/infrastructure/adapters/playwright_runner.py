from __future__ import annotations

import sys
import time
from pathlib import Path

# Use the venv's Playwright: resolve relative to this repo, not a hardcoded path.
def _ensure_playwright_path():
    # Walk up from this file to find the repo root (contains .venv or pyproject)
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        venv_site = parent / ".venv" / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        if venv_site.is_dir() and str(venv_site) not in sys.path:
            sys.path.insert(0, str(venv_site))
            return
        # Also try plain .venv/lib/python3*/site-packages glob
        venv_lib = parent / ".venv" / "lib"
        if venv_lib.is_dir():
            for site in venv_lib.glob("python*/site-packages"):
                if site.is_dir() and str(site) not in sys.path:
                    sys.path.insert(0, str(site))
                    return

_ensure_playwright_path()

_SESSION_TTL = 300  # 5 minutes


class PlaywrightRunnerAdapter:
    """Headless Chromium automation via Playwright.

    Sessions are cached per-URL so that browser_fill -> browser_submit
    share the same page (filled values persist). Sessions expire after
    _SESSION_TTL seconds. load_page_text() remains stateless.
    """

    def __init__(self):
        # url -> {"pw": playwright, "browser": browser, "page": page, "ts": float}
        self._sessions: dict = {}

    def _launch(self, p):
        return p.chromium.launch(headless=True)

    def _get_session(self, url: str):
        """Return (page, is_new). Reuses cached session if fresh."""
        from playwright.sync_api import sync_playwright

        now = time.time()
        # Expire stale sessions
        stale = [u for u, s in self._sessions.items() if now - s["ts"] > _SESSION_TTL]
        for u in stale:
            self._close_session(u)

        if url in self._sessions:
            sess = self._sessions[url]
            sess["ts"] = now  # refresh
            return sess["page"], False

        # New session
        pw = sync_playwright().start()
        browser = self._launch(pw)
        page = browser.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        self._sessions[url] = {"pw": pw, "browser": browser, "page": page, "ts": now}
        return page, True

    def _close_session(self, url: str):
        sess = self._sessions.pop(url, None)
        if not sess:
            return
        try:
            sess["browser"].close()
        except Exception:
            pass
        try:
            sess["pw"].stop()
        except Exception:
            pass

    def close_all_sessions(self):
        for url in list(self._sessions.keys()):
            self._close_session(url)

    def load_page_text(self, url: str, max_chars: int = 8000) -> dict:
        # Stateless: fresh browser per call (read-only, no session needed).
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = self._launch(p)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=30000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    title = page.title()
                    text = page.inner_text("body")[:max_chars]
                    return {"ok": True, "title": title, "text": text}
                finally:
                    browser.close()
        except Exception as e:
            return {"ok": False, "message": f"Browser error: {e}", "evidence": {}}

    def fill_fields(self, url: str, fields: dict) -> dict:
        try:
            page, _ = self._get_session(url)
            filled = []
            for selector, value in fields.items():
                try:
                    page.fill(selector, str(value), timeout=10000)
                    filled.append(selector)
                except Exception as e:
                    return {
                        "ok": False,
                        "message": f"Failed to fill {selector}: {e}",
                        "evidence": {"filled": filled},
                    }
            return {"ok": True, "filled": filled,
                    "message": f"Filled {len(filled)} fields (session kept for submit)."}
        except Exception as e:
            self._close_session(url)
            return {"ok": False, "message": f"Browser error: {e}", "evidence": {}}

    def click_submit(self, url: str, selector: str) -> dict:
        try:
            page, is_new = self._get_session(url)
            # If this is a fresh session (no prior fill), the page was just loaded.
            # If reused, it already has the filled values.
            page.click(selector, timeout=10000)
            page.wait_for_timeout(3000)
            text = page.inner_text("body")[:2000]
            # Session is single-use for submit: close after submit to avoid stale state.
            self._close_session(url)
            return {"ok": True, "result_text": text,
                    "message": "Submit clicked (session closed).",
                    "evidence": {"reused_fill_session": not is_new}}
        except Exception as e:
            self._close_session(url)
            return {"ok": False, "message": f"Browser error: {e}", "evidence": {}}
