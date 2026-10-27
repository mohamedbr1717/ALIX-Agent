"""Verifier port (Decision 2 seam — stubbed in Decision 1).

After a step's tool returns ok, the verifier decides whether the
step counts as SUCCEEDED. Decision 1 ships only the default
``ContractOkVerifier`` (infrastructure), which trusts the result
contract's ``ok`` flag. Read-back verification with three-valued
verdicts (VERIFIED/FAILED/UNKNOWN) is Decision 2 and plugs in
here without touching the executor.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from domain.planning.entities import PlanStep


class VerifierPort(ABC):
    """Post-dispatch check for one executed step."""

    @abstractmethod
    def verify(self, step: PlanStep, result: dict) -> bool:
        """True => the step may transition to SUCCEEDED."""
