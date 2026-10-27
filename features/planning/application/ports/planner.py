"""Planner port: the model's ONLY two entrances into planning.

Both methods return the RAW draft (a dict) — untrusted input that
the domain validation must accept before anything is stored or
executed (spec §4.6). Implementations may raise on transport
failure; callers treat any raise as a rejected draft.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from domain.planning.entities import PlanStep, PriorAction


class PlannerPort(ABC):
    """Produces plan drafts and failure decompositions."""

    @abstractmethod
    def plan(
        self,
        goal: str,
        prior_actions: List[PriorAction],
        context: dict,
    ) -> dict:
        """Draft a plan for ``goal``: {"steps": [{intent, tool, args}]}.

        ``context`` carries the tool allowlist + argument schemas
        the draft must respect (validation still enforces them).
        """

    @abstractmethod
    def decompose(
        self,
        goal: str,
        failed_step: PlanStep,
        remaining_steps: List[PlanStep],
    ) -> dict:
        """React to one failed step. Returns one of:
        {"mode": "decompose", "steps": [...]},
        {"mode": "rewrite_tail", "steps": [...]},
        {"mode": "give_up"} — or anything else, which the hook
        treats as giving up (fail-closed).
        """
