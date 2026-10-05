from __future__ import annotations

import sys
from pathlib import Path

# Use the venv's Playwright
_VENV_SITE = Path("/home/ubuntu/ALIX-Agent/.venv/lib/python3.12/site-packages")
if _VENV_SITE.is_dir() and str(_VENV_SITE) not in sys.path:
    sys.path.insert(0, str(_VENV_SITE))


class PlaywrightRunnerAdapter:
    """Headless Chromium automation via Playwright."""

    def _launch(self, p):
        return p.chromium.launch(headless=True)

    def load_page_text(self, url: str, max_chars: int = 8000) -> dict:
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
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = self._launch(p)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=30000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
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
                            "message": f"Filled {len(filled)} fields (not submitted)."}
                finally:
                    browser.close()
        except Exception as e:
            return {"ok": False, "message": f"Browser error: {e}", "evidence": {}}

    def click_submit(self, url: str, selector: str) -> dict:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = self._launch(p)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=30000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    page.click(selector, timeout=10000)
                    page.wait_for_timeout(3000)
                    text = page.inner_text("body")[:2000]
                    return {"ok": True, "result_text": text,
                            "message": "Submit clicked."}
                finally:
                    browser.close()
        except Exception as e:
            return {"ok": False, "message": f"Browser error: {e}", "evidence": {}}
