from __future__ import annotations


class WebSearchAuthorizationAdapter:
    """Authorization: a search needs a non-empty query string."""

    def can_search(self, query: str) -> bool:
        return isinstance(query, str) and bool(query.strip())
