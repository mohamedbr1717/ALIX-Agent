"""DTOs for the planning slice.

Records are the persisted shape of a plan (frozen dataclasses
with to_dict/from_dict, mirroring TaskRecord in the scheduler
slice). They reflect the domain fields of spec §2.2/§2.3 exactly;
the reserved ``verify``/``compensate`` fields are copied verbatim
and never interpreted in Decision 1. ``PlanRecord.state`` is the
derived plan state at save time — informational for human
readers; the domain derivation is recomputed on every load and
remains the only source of truth (spec §2.5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class PriorActionRecord:
    tool: str
    args_hash: str
    result_ref: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args_hash": self.args_hash,
            "result_ref": self.result_ref,
        }

    @staticmethod
    def from_dict(data: dict) -> "PriorActionRecord":
        return PriorActionRecord(
            tool=str(data["tool"]),
            args_hash=str(data.get("args_hash", "")),
            result_ref=str(data.get("result_ref", "")),
        )


@dataclass(frozen=True)
class PlanStepRecord:
    step_id: str
    intent: str
    tool: str
    args: dict = field(default_factory=dict)
    state: str = "pending"
    depth: int = 0
    parent_step_id: Optional[str] = None
    attempts: int = 0
    idempotency_key: str = ""
    result_ref: Optional[str] = None
    error: Optional[str] = None
    blocked_reason: Optional[str] = None
    outcome_unknown: bool = False
    resolved_by_decomposition: bool = False
    verify: Optional[dict] = None
    verify_outcome: Optional[dict] = None
    compensate: Optional[dict] = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "intent": self.intent,
            "tool": self.tool,
            "args": dict(self.args),
            "state": self.state,
            "depth": self.depth,
            "parent_step_id": self.parent_step_id,
            "attempts": self.attempts,
            "idempotency_key": self.idempotency_key,
            "result_ref": self.result_ref,
            "error": self.error,
            "blocked_reason": self.blocked_reason,
            "outcome_unknown": self.outcome_unknown,
            "resolved_by_decomposition": (
                self.resolved_by_decomposition
            ),
            "verify": self.verify,
            "verify_outcome": self.verify_outcome,
            "compensate": self.compensate,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "PlanStepRecord":
        args = data.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ValueError("step args must be an object")
        return PlanStepRecord(
            step_id=str(data["step_id"]),
            intent=str(data.get("intent", "")),
            tool=str(data["tool"]),
            args=dict(args),
            state=str(data.get("state", "pending")),
            depth=int(data.get("depth", 0)),
            parent_step_id=data.get("parent_step_id"),
            attempts=int(data.get("attempts", 0)),
            idempotency_key=str(
                data.get("idempotency_key", "")
            ),
            result_ref=data.get("result_ref"),
            error=data.get("error"),
            blocked_reason=data.get("blocked_reason"),
            outcome_unknown=bool(
                data.get("outcome_unknown", False)
            ),
            resolved_by_decomposition=bool(
                data.get("resolved_by_decomposition", False)
            ),
            verify=data.get("verify"),
            verify_outcome=data.get("verify_outcome"),
            compensate=data.get("compensate"),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass(frozen=True)
class PlanRecord:
    plan_id: str
    goal: str
    origin: str
    steps: tuple = ()
    prior_actions: tuple = ()
    replans_used: int = 0
    replans_max: int = 2
    awaiting_step_id: Optional[str] = None
    escalated: bool = False
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    #: Derived state at save time (informational only).
    state: str = "pending"

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "origin": self.origin,
            "steps": [s.to_dict() for s in self.steps],
            "prior_actions": [
                p.to_dict() for p in self.prior_actions
            ],
            "replans_used": self.replans_used,
            "replans_max": self.replans_max,
            "awaiting_step_id": self.awaiting_step_id,
            "escalated": self.escalated,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "state": self.state,
        }

    @staticmethod
    def from_dict(data: dict) -> "PlanRecord":
        raw_steps = data.get("steps", [])
        if not isinstance(raw_steps, list):
            raise ValueError("plan steps must be a list")
        raw_prior = data.get("prior_actions", [])
        if not isinstance(raw_prior, list):
            raise ValueError("prior_actions must be a list")
        return PlanRecord(
            plan_id=str(data["plan_id"]),
            goal=str(data.get("goal", "")),
            origin=str(data.get("origin", "interactive")),
            steps=tuple(
                PlanStepRecord.from_dict(item)
                for item in raw_steps
                if isinstance(item, dict)
            ),
            prior_actions=tuple(
                PriorActionRecord.from_dict(item)
                for item in raw_prior
                if isinstance(item, dict)
            ),
            replans_used=int(data.get("replans_used", 0)),
            replans_max=int(data.get("replans_max", 2)),
            awaiting_step_id=data.get("awaiting_step_id"),
            escalated=bool(data.get("escalated", False)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            expires_at=str(data.get("expires_at", "")),
            state=str(data.get("state", "pending")),
        )


# ---------------------------------------------------------
# Requests
# ---------------------------------------------------------


@dataclass(frozen=True)
class CreatePlanRequest:
    goal: str
    origin: str  # "interactive" | "scheduled"
    #: Raw interactive executions before escalation:
    #: (tool, arguments, raw_result_text) triples. The use case
    #: converts them to PriorAction records (hash + summary).
    prior_actions: tuple = ()
    #: Creation-policy floor (spec §9.1 default): the automatic
    #: round-3 escalation passes 2 — a one-step remainder is not
    #: worth a plan and falls back to plain ReAct.
    min_steps: int = 1


@dataclass(frozen=True)
class GetPlanRequest:
    plan_id: str


@dataclass(frozen=True)
class ListPlansRequest:
    include_finished: bool = False


@dataclass(frozen=True)
class CancelPlanRequest:
    plan_id: str
