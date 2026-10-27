"""PlanNotifier: PlanNotifierPort implementation (interfaces).

Renders each semantic event with the pure formatters and
delivers the text two ways: (1) an optional injected sender —
production wiring passes core.scheduled_approval.notify_user,
whose outbox the Telegram bot polls and delivers; (2) an
in-memory buffer the caller can drain (the agent folds drained
texts into its reply, which is the CLI delivery channel).

A failing sender NEVER propagates: notification failure must
not fail a plan (port contract).
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Callable, List, Optional

from domain.planning.entities import Plan, PlanStep

from features.planning.application.ports.plan_notifier import (
    PlanNotifierPort,
)
from features.planning.interfaces import formatting


class PlanNotifier(PlanNotifierPort):
    def __init__(
        self,
        sender: Optional[Callable] = None,
        clock: Optional[Callable] = None,
    ):
        self._sender = sender
        self._clock = clock or (
            lambda: datetime.now().astimezone()
        )
        self._buffer: List[str] = []

    # ---------------------------------------------------------

    def drain(self) -> List[str]:
        """Return buffered texts and clear the buffer."""
        texts, self._buffer = self._buffer, []
        return texts

    # ---------------------------------------------------------
    # PlanNotifierPort
    # ---------------------------------------------------------

    def created(self, plan: Plan, approval_steps: int) -> None:
        self._emit(
            formatting.format_plan_created(
                plan, approval_steps, self._clock()
            )
        )

    def decomposed(
        self,
        plan: Plan,
        failed_step: PlanStep,
        new_step_ids: List[str],
    ) -> None:
        self._emit(
            formatting.format_decomposition(
                plan, failed_step, new_step_ids, self._clock()
            )
        )

    def escalated(
        self,
        plan: Plan,
        failed_step: PlanStep | None,
        reason: str,
    ) -> None:
        self._emit(
            formatting.format_escalation(
                plan, failed_step, reason, self._clock()
            )
        )

    def finished(self, plan: Plan) -> None:
        self._emit(
            formatting.format_finished(plan, self._clock())
        )

    def recovered(self, plans: List[Plan]) -> None:
        self._emit(
            formatting.format_recovery(plans, self._clock())
        )

    # ---------------------------------------------------------

    def _emit(self, text: str) -> None:
        self._buffer.append(text)
        if self._sender is not None:
            try:
                self._sender(text)
            except Exception as exc:  # never break a plan
                print(
                    f"[planning] notification failed: {exc}",
                    file=sys.stderr,
                )
