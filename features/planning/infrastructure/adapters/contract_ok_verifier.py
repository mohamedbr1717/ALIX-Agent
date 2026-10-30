"""Default verifier (Decision 1 semantics, Decision 2 signature).

``ContractOkVerifier`` accepts a step iff its tool result says
``ok`` — the same contract every ALIX tool already returns
(SCHEMA_CONTRACT.md). It remains the verifier for seams that have
no read-back wiring; plan execution in production uses the
read-back verifier (Decision 2), which distrusts this flag and
re-reads the world instead.
"""
from __future__ import annotations

from domain.planning.entities import PlanStep

from features.planning.application.ports.verifier import (
    VerificationOutcome,
    Verdict,
    VerifierPort,
)


class ContractOkVerifier(VerifierPort):
    def verify(
        self, step: PlanStep, result: dict
    ) -> VerificationOutcome:
        ok = (
            isinstance(result, dict)
            and result.get("ok") is True
        )
        return VerificationOutcome(
            verdict=Verdict.VERIFIED if ok else Verdict.FAILED,
            channel="contract",
            observed="contract ok" if ok else "contract not ok",
        )
