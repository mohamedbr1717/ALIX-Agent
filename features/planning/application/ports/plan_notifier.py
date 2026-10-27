"""Owner-notification port for plan lifecycle events.

Exactly four event types are worth a message (spec §5.1) plus the
startup recovery digest; step-by-step progress is pull-only via
plan_status, never pushed. Implementations must not raise into
the executor: a failed notification never fails a plan.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from domain.planning.entities import Plan, PlanStep


class PlanNotifierPort(ABC):
    """Semantic plan events, rendered by the implementation."""

    @abstractmethod
    def created(self, plan: Plan, approval_steps: int) -> None:
        """A new multi-step plan exists (steps + approval count)."""

    @abstractmethod
    def decomposed(
        self,
        plan: Plan,
        failed_step: PlanStep,
        new_step_ids: List[str],
    ) -> None:
        """A failed step was decomposed / the tail was rewritten."""

    @abstractmethod
    def escalated(
        self,
        plan: Plan,
        failed_step: PlanStep | None,
        reason: str,
    ) -> None:
        """The plan stopped and needs the owner (budget out,
        planner gave up, unknown outcome after a crash, ...)."""

    @abstractmethod
    def finished(self, plan: Plan) -> None:
        """The plan completed or stopped blocked."""

    @abstractmethod
    def recovered(self, plans: List[Plan]) -> None:
        """One combined startup digest of crash-normalized plans."""
