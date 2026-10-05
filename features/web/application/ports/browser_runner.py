from __future__ import annotations

from abc import ABC, abstractmethod


class BrowserRunnerPort(ABC):
    """Playwright-backed browser automation."""

    @abstractmethod
    def load_page_text(self, url: str, max_chars: int) -> dict:
        """Navigate to URL, return {ok, text, title}."""

    @abstractmethod
    def fill_fields(self, url: str, fields: dict) -> dict:
        """Fill form fields without submitting. Return {ok, filled}."""

    @abstractmethod
    def click_submit(self, url: str, selector: str) -> dict:
        """Click a submit button. Return {ok, result_text}."""
