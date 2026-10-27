"""Planning enumerations (Decision 1 — pure domain, stdlib only).

The step/plan vocabularies live here so entities, transitions,
derivation and validation all speak exactly the same language.
"""
from __future__ import annotations

from enum import Enum


class StepState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


#: States a step can never leave once reached (spec §2.4).
TERMINAL_STEP_STATES = frozenset(
    {StepState.SUCCEEDED, StepState.FAILED, StepState.SKIPPED}
)


class BlockedReason(Enum):
    SCHEDULED_POLICY = "scheduled_policy"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_INTERRUPTED = "approval_interrupted"
    INTERRUPTED_UNKNOWN_OUTCOME = "interrupted_unknown_outcome"
    DEPENDENCY_HALTED = "dependency_halted"


class PlanState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    ESCALATED = "escalated"
    EXPIRED = "expired"
