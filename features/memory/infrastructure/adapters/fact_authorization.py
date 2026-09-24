from __future__ import annotations

from core.prompt_guard import scan


class FactAuthorizationAdapter:
    """Authorization: a fact needs non-empty text without injections."""

    def can_remember(self, fact: str) -> bool:
        if not isinstance(fact, str) or not fact.strip():
            return False
        # Deny facts carrying high-severity injections (memory poisoning).
        findings = scan(fact)
        return not any(f.severity == "high" for f in findings)
