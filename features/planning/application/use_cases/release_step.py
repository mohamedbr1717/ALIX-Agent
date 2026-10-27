"""release_step use case: owner-only unblock of a BLOCKED step.

This is the controller-level owner command of spec §3.3/§5.2 —
deliberately NOT an LLM tool in Decision 1 (no plan_resume):
releasing a step whose outcome may be unknown is a human
decision, and Decision 3 will add read-back before release for
the INTERRUPTED_UNKNOWN_OUTCOME case.
"""
from __future__ import annotations

import time
from typing import Callable

from domain.planning.states import StepState

from features.planning.application.mapping import (
    plan_to_record,
    record_to_plan,
)
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.use_cases.helpers import iso


class ReleaseStepUseCase:
    def __init__(self, *, store: PlanStorePort, clock: Callable):
        self._store = store
        self._clock = clock

    def execute(self, plan_id: str, step_id: str) -> dict:
        started = time.monotonic()

        record = self._store.get((plan_id or "").strip())
        if record is None:
            return self._deny(
                started, f"لا توجد خطة بالمعرّف {plan_id}."
            )

        now = self._clock()
        plan = record_to_plan(record, now)

        try:
            step = plan.step((step_id or "").strip())
        except KeyError:
            return self._deny(
                started,
                f"لا توجد خطوة بالمعرّف {step_id} "
                f"في الخطة {plan.plan_id}.",
            )

        if step.state is not StepState.BLOCKED:
            return self._deny(
                started,
                f"الخطوة {step.step_id} ليست محظورة "
                f"(حالتها {step.state.value}).",
            )

        # BLOCKED -> PENDING (owner release only, spec §2.4).
        # outcome_unknown is historical until the step actually
        # re-enters RUNNING, where the fresh dispatch supersedes
        # it (entities.PlanStep.transition).
        step.transition(StepState.PENDING, now=iso(now))
        plan.updated_at = iso(now)
        self._store.save(plan_to_record(plan, now))

        return {
            "ok": True,
            "action": "plan_release_step",
            "message": (
                f"حُرّرت الخطوة {step.step_id} "
                f"في الخطة {plan.plan_id}."
            ),
            "plan": plan_to_record(plan, now).to_dict(),
            "evidence": {},
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        return {
            "ok": False,
            "action": "plan_release_step",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
