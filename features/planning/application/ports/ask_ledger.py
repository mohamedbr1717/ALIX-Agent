"""AskLedgerPort (single-ask principle, 2026-11-01).

Records when a scheduled clarification was last DELIVERED
for a goal key, so CreatePlan can ask once and then stay
silent until the cooldown passes. Pure bookkeeping: the
ledger never decides policy — the cooldown rule lives in
CreatePlanUseCase; implementations only store timestamps.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class AskLedgerPort(ABC):
    @abstractmethod
    def last_asked(self, key: str) -> Optional[datetime]:
        """When the ask for `key` was last delivered (aware
        datetime), or None when it was never asked."""
        raise NotImplementedError

    @abstractmethod
    def record(self, key: str, when: datetime) -> None:
        """Mark `key` as asked at `when`. Best-effort: a
        bookkeeping failure must never break plan creation."""
        raise NotImplementedError
