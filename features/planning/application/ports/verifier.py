"""Verifier port (Decision 2).

After a step's tool returns ok, the verifier decides whether the
step counts as SUCCEEDED. Decision 1 shipped only the default
``ContractOkVerifier`` (infrastructure), which trusts the result
contract's ``ok`` flag. Decision 2 adds the read-back verifier
behind this same port: it re-reads the world through an
independent channel and returns a three-valued verdict —
VERIFIED (the effect is proven), FAILED (the read-back positively
contradicts the claimed effect), UNKNOWN (no usable evidence).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from domain.planning.entities import PlanStep


class Verdict(Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VerificationOutcome:
    """One verifier judgment, with the evidence it rests on."""

    verdict: Verdict
    #: How the evidence was gathered: a read tool name, the
    #: internal channel name ("memory"), "contract" for the
    #: ok-trusting default, or "exempt" for steps that need no
    #: read-back (pure reads, notify).
    channel: str = ""
    predicate: str = ""
    #: Short human-readable summary of what was observed — this is
    #: what reaches the owner in an escalation, one line.
    observed: str = ""

    def to_record(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "channel": self.channel,
            "predicate": self.predicate,
            "observed": self.observed,
        }


class VerifierPort(ABC):
    """Post-dispatch check for one executed step."""

    @abstractmethod
    def verify(
        self, step: PlanStep, result: dict
    ) -> VerificationOutcome:
        """Judge the step's claimed effect.

        VERIFIED => the step may transition to SUCCEEDED.
        FAILED => the step failed (its effect is disproven).
        UNKNOWN => the outcome cannot be established.
        """
        ...
