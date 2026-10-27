"""Store port for plans (spec §3.2)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from features.planning.application.dto.planning import PlanRecord


class PlanStorePort(ABC):
    """Persistence for plan records (JSON file in production).

    ``save`` upserts one record by plan_id; the store owns the
    full-list read/modify/write cycle and its atomicity.
    """

    @abstractmethod
    def save(self, record: PlanRecord) -> None:
        """Atomically persist one plan record (insert or replace)."""

    @abstractmethod
    def get(self, plan_id: str) -> Optional[PlanRecord]:
        """Return one plan record, or None when absent."""

    @abstractmethod
    def list_all(self) -> List[PlanRecord]:
        """Return all stored plan records."""
