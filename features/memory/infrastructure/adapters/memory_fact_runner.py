from __future__ import annotations

from typing import Any


class MemoryFactRunnerAdapter:
    """Runner delegating to the Memory store's add_fact/add_preference
    (sanitization, dedup, and persistence live in core/memory.py)."""

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    def run_remember(self, fact: str, is_preference: bool) -> dict:
        if is_preference:
            saved = self._memory.add_preference(fact)
        else:
            saved = self._memory.add_fact(fact)
        return {
            "ok": bool(saved),
            "evidence": {
                "saved": bool(saved),
                "type": "preference" if is_preference else "fact",
            },
        }
