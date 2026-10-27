"""Legal step transitions for plans (Decision 1 — pure domain).

Fail-closed, exactly like Policy: a transition absent from the
table is not "probably fine", it is forbidden and raises
``IllegalTransition``. The executor never invents a move the table
does not list.
"""
from __future__ import annotations

from .states import StepState


class IllegalTransition(ValueError):
    """Raised when a step transition is not in the legal table."""


class InvariantViolation(ValueError):
    """Raised when a plan invariant (spec §2.6) would be broken."""


#: The legal-transition table (spec §2.4). RUNNING -> BLOCKED exists
#: ONLY as the load-time crash-normalization rule (§3.3); the
#: executor never performs it during a run.
LEGAL_TRANSITIONS: dict[StepState, frozenset] = {
    StepState.PENDING: frozenset(
        {StepState.RUNNING, StepState.BLOCKED, StepState.SKIPPED}
    ),
    StepState.RUNNING: frozenset(
        {StepState.SUCCEEDED, StepState.FAILED, StepState.BLOCKED}
    ),
    StepState.SUCCEEDED: frozenset(),
    StepState.FAILED: frozenset(),
    StepState.BLOCKED: frozenset(
        {StepState.PENDING, StepState.SKIPPED}
    ),
    StepState.SKIPPED: frozenset(),
}


def can_transition(current: StepState, target: StepState) -> bool:
    """True iff ``current -> target`` is a legal step transition."""
    return target in LEGAL_TRANSITIONS.get(current, frozenset())


def assert_transition(current: StepState, target: StepState) -> None:
    """Raise IllegalTransition unless the move is in the table."""
    if not can_transition(current, target):
        raise IllegalTransition(
            f"illegal plan step transition: "
            f"{current.value!r} -> {target.value!r}"
        )
