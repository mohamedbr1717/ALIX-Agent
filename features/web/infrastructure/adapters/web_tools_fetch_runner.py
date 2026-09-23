from __future__ import annotations

from tools.web import WebTools


class WebToolsFetchRunnerAdapter:
    """Runner delegating to the hardened WebTools.web_fetch
    (SSRF guard with per-hop re-validation, size caps)."""

    def __init__(self) -> None:
        self._tools = WebTools()

    def run_fetch(self, url: str, max_chars: int) -> dict:
        return self._tools.web_fetch(url, max_chars)
