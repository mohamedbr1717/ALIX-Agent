"""Default verifier (Decision 1): trust the result contract.

``ContractOkVerifier`` accepts a step iff its tool result says
``ok`` — the same contract every ALIX tool already returns
(SCHEMA_CONTRACT.md). Real outcome verification (read-back,
three-valued verdicts) is Decision 2 and replaces this adapter
behind VerifierPort without touching the executor.
"""
from __future__ import annotations

from domain.planning.entities import PlanStep

from features.planning.application.ports.verifier import (
    VerifierPort,
)


class ContractOkVerifier(VerifierPort):
    def verify(self, step: PlanStep, result: dict) -> bool:
        return (
            isinstance(result, dict)
            and result.get("ok") is True
        )
