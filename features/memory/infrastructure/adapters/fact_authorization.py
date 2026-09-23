from __future__ import annotations


class FactAuthorizationAdapter:
    """Authorization: a fact needs non-empty text."""

    def can_remember(self, fact: str) -> bool:
        return isinstance(fact, str) and bool(fact.strip())
