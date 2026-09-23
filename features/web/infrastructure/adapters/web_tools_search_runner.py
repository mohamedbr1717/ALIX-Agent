from __future__ import annotations

from tools.web import WebTools


class WebToolsSearchRunnerAdapter:
    """Runner delegating to the hardened WebTools.web_search
    (DDG -> Lite -> Bing chain, no API key)."""

    def __init__(self) -> None:
        self._tools = WebTools()

    def run_search(self, query: str, max_results: int) -> dict:
        return self._tools.web_search(query, max_results)
