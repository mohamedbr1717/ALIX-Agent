"""Plan / PlanStep entities (Decision 1 — pure domain).

A Plan is the persistent unit of multi-step work: an ordered list
of steps executed strictly in order by a deterministic executor.
The entities own the step state machine and the plan invariants
(spec §2.6); they know nothing about JSON, files, LLMs or Policy —
timestamps are ISO strings supplied by the Application layer (the
domain never reads a clock).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .states import BlockedReason, StepState
from .transitions import (
    InvariantViolation,
    assert_transition,
)

#: Hard code-enforced limits (spec §2.6 / §4.5). These are budget
#: guards in code, never instructions to the model.
MAX_DEPTH = 2
REPLANS_MAX = 2
MAX_STEPS_PER_PLAN = 12
MAX_SUBSTEPS = 4
MAX_TOTAL_STEPS = 20
PLAN_TTL_HOURS = 24

#: Result summaries / error texts are stored truncated (spec §9.3).
MAX_STORED_TEXT_CHARS = 500


@dataclass
class PriorAction:
    """A tool execution that already happened interactively (ReAct)
    before the goal escalated to a plan. Historical record only —
    no state machine (spec §2.3)."""

    tool: str
    args_hash: str
    result_ref: str = ""


@dataclass
class PlanStep:
    """One step of a plan: intent for the owner, tool for the
    executor, and the full bookkeeping the later decisions need."""

    step_id: str
    intent: str
    tool: str
    args: dict = field(default_factory=dict)
    state: StepState = StepState.PENDING
    depth: int = 0
    parent_step_id: Optional[str] = None
    attempts: int = 0
    idempotency_key: str = ""
    result_ref: Optional[str] = None
    error: Optional[str] = None
    blocked_reason: Optional[BlockedReason] = None
    outcome_unknown: bool = False
    resolved_by_decomposition: bool = False
    #: Decision 2 (verification): the read-back spec for this step
    #: (decision-02 spec §2) and its recorded outcome — the verdict
    #: dict the verifier produced, or None when the step has not
    #: been verified (or predates Decision 2).
    verify: Optional[dict] = None
    verify_outcome: Optional[dict] = None
    #: Reserved for Decision 3 (recovery/saga) — opaque in Decision 1.
    compensate: Optional[dict] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("plan step id must not be empty")
        if self.args is None:
            self.args = {}
        if not isinstance(self.args, dict):
            raise TypeError("plan step args must be a dict")
        self._check_blocked_reason()

    def _check_blocked_reason(self) -> None:
        # Invariant §2.6.10: BLOCKED <=> blocked_reason present.
        if self.state is StepState.BLOCKED:
            if self.blocked_reason is None:
                raise InvariantViolation(
                    f"step {self.step_id!r} is BLOCKED "
                    "without a blocked_reason"
                )
        elif self.blocked_reason is not None:
            raise InvariantViolation(
                f"step {self.step_id!r} is {self.state.value} "
                "but carries a blocked_reason"
            )

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            StepState.SUCCEEDED,
            StepState.FAILED,
            StepState.SKIPPED,
        )

    def transition(
        self,
        target: StepState,
        *,
        blocked_reason: Optional[BlockedReason] = None,
        now: str = "",
    ) -> None:
        """Move this step to ``target``, enforcing the table.

        Entering BLOCKED requires a reason; leaving BLOCKED clears
        it. Entering RUNNING counts an attempt and supersedes any
        earlier unknown outcome (a fresh dispatch replaces it).
        """
        assert_transition(self.state, target)

        if target is StepState.BLOCKED:
            if blocked_reason is None:
                raise InvariantViolation(
                    f"step {self.step_id!r}: entering BLOCKED "
                    "requires a blocked_reason"
                )
            self.blocked_reason = blocked_reason
        elif self.state is StepState.BLOCKED:
            self.blocked_reason = None

        if target is StepState.RUNNING:
            self.attempts += 1
            self.outcome_unknown = False

        self.state = target
        if now:
            self.updated_at = now
        self._check_blocked_reason()


@dataclass
class Plan:
    """An ordered, persistent plan for one multi-step goal."""

    plan_id: str
    goal: str
    origin: str  # "interactive" | "scheduled"
    steps: list = field(default_factory=list)
    prior_actions: list = field(default_factory=list)
    replans_used: int = 0
    replans_max: int = REPLANS_MAX
    awaiting_step_id: Optional[str] = None
    escalated: bool = False
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("plan id must not be empty")
        if self.origin not in ("interactive", "scheduled"):
            raise ValueError(
                f"unknown plan origin: {self.origin!r}"
            )
        self.validate_invariants()

    # ---------------------------------------------------------
    # Lookups
    # ---------------------------------------------------------

    def step(self, step_id: str) -> PlanStep:
        """Return the step with ``step_id`` (KeyError if absent)."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(f"no plan step with id {step_id!r}")

    def step_index(self, step_id: str) -> int:
        for index, step in enumerate(self.steps):
            if step.step_id == step_id:
                return index
        raise KeyError(f"no plan step with id {step_id!r}")

    # ---------------------------------------------------------
    # Transitions with plan-level invariants
    # ---------------------------------------------------------

    def transition_step(
        self,
        step_id: str,
        target: StepState,
        *,
        blocked_reason: Optional[BlockedReason] = None,
        now: str = "",
    ) -> PlanStep:
        """Transition one step, enforcing plan-level invariants.

        Entering RUNNING additionally enforces §2.6.2 (at most one
        running step) and §2.6.3 (strict order: the step must be
        the next runnable one — no jumping over a blocked or
        unresolved-failed step).
        """
        step = self.step(step_id)

        if target is StepState.RUNNING:
            for other in self.steps:
                if (
                    other is not step
                    and other.state is StepState.RUNNING
                ):
                    raise InvariantViolation(
                        f"plan {self.plan_id!r}: step "
                        f"{other.step_id!r} is already RUNNING"
                    )
            from .derivation import next_runnable_step

            if next_runnable_step(self) is not step:
                raise InvariantViolation(
                    f"plan {self.plan_id!r}: step {step_id!r} "
                    "is not the next runnable step"
                )

        step.transition(
            target, blocked_reason=blocked_reason, now=now
        )
        if now:
            self.updated_at = now
        return step

    # ---------------------------------------------------------
    # Invariants (spec §2.6)
    # ---------------------------------------------------------

    def validate_invariants(self) -> None:
        if not self.steps:
            raise InvariantViolation(
                f"plan {self.plan_id!r} must hold >= 1 step"
            )
        if len(self.steps) > MAX_TOTAL_STEPS:
            raise InvariantViolation(
                f"plan {self.plan_id!r} exceeds "
                f"MAX_TOTAL_STEPS={MAX_TOTAL_STEPS}"
            )
        if not (0 <= self.replans_used <= self.replans_max):
            raise InvariantViolation(
                f"plan {self.plan_id!r}: replans_used="
                f"{self.replans_used} outside "
                f"[0, {self.replans_max}]"
            )

        seen_ids = set()
        seen_keys = set()
        running = 0
        for step in self.steps:
            if step.step_id in seen_ids:
                raise InvariantViolation(
                    f"duplicate step id: {step.step_id!r}"
                )
            seen_ids.add(step.step_id)

            expected_key = f"{self.plan_id}:{step.step_id}"
            if step.idempotency_key != expected_key:
                raise InvariantViolation(
                    f"step {step.step_id!r}: idempotency_key "
                    f"{step.idempotency_key!r} != {expected_key!r}"
                )
            if step.idempotency_key in seen_keys:
                raise InvariantViolation(
                    f"duplicate idempotency_key: "
                    f"{step.idempotency_key!r}"
                )
            seen_keys.add(step.idempotency_key)

            if step.depth > MAX_DEPTH:
                raise InvariantViolation(
                    f"step {step.step_id!r}: depth {step.depth} "
                    f"> MAX_DEPTH={MAX_DEPTH}"
                )
            if step.state is StepState.RUNNING:
                running += 1
            step._check_blocked_reason()

        if running > 1:
            raise InvariantViolation(
                f"plan {self.plan_id!r}: {running} steps RUNNING"
            )


def substep_id(parent_step_id: str, index: int) -> str:
    """Derived substep id: ``s3`` -> ``s3.1``, ``s3.2``, ..."""
    return f"{parent_step_id}.{index}"
