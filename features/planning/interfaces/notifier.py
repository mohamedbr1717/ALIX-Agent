"""PlanNotifier: PlanNotifierPort implementation (interfaces).

Renders each semantic event with the pure formatters and
delivers the text through exactly one channel: (1) an optional
injected sender — production wiring passes
core.scheduled_approval.notify_user, whose outbox the Telegram
bot polls and delivers; (2) only when no sender is injected, or
the sender raises, an in-memory buffer the caller can drain
(the agent folds drained texts into its reply, which is the CLI
delivery channel). The channels are exclusive on purpose: in
Telegram both terminate in the same chat, so delivering through
both duplicates every plan message.

One refinement (single-delivery fix, 2026-11-01): exclusivity
by wiring alone was not enough — with a sender wired, the
buffer stayed empty and the controller's empty-buffer fallback
re-sent a clarification as the turn's reply, so the owner got
it twice (outbox + reply). Callers whose reply IS the channel
(interactive turns) now open a buffering() window: inside it,
emission goes to the buffer even with a sender wired, and the
reply carries each event exactly once.

A failing sender NEVER propagates: notification failure must
not fail a plan (port contract) — the text falls back to the
buffer instead.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
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
        self._buffer_depth = 0

    # ---------------------------------------------------------

    def drain(self) -> List[str]:
        """Return buffered texts and clear the buffer."""
        texts, self._buffer = self._buffer, []
        return texts

    @contextmanager
    def buffering(self):
        """Buffer-only window (single-delivery fix, 2026-11-01).

        While active, emitted texts go to the in-memory buffer
        even when a sender is wired, so the caller can deliver
        them through its own reply — one channel for the whole
        turn. Nesting-safe; the depth always restores, even on
        exceptions."""
        self._buffer_depth += 1
        try:
            yield
        finally:
            self._buffer_depth -= 1

    # ---------------------------------------------------------
    # PlanNotifierPort
    # ---------------------------------------------------------

    def created(self, plan: Plan, approval_steps: int) -> None:
        self._emit(
            formatting.format_plan_created(
                plan, approval_steps, self._clock()
            )
        )

    def clarification(self, goal: str, question: str) -> None:
        # Decision 6: the ask reaches the owner through the
        # same buffered channel as every other plan event.
        self._emit(
            f"❓ توضيح مطلوب قبل التنفيذ: «{goal}»\n{question}"
        )

    def plan_notices(self, plan: Plan, notices) -> None:
        if notices:
            self._emit("\n".join(notices))

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
        if self._buffer_depth == 0 and self._sender is not None:
            try:
                self._sender(text)
                return
            except Exception as exc:  # never break a plan
                print(
                    f"[planning] notification failed: {exc}",
                    file=sys.stderr,
                )
        self._buffer.append(text)
