"""cancel_plan use case (backs the plan_cancel tool).

Cancellation is a state move, not a deletion: every PENDING or
BLOCKED step becomes SKIPPED; terminal steps are history and
stay untouched. The plan record itself is kept (audit).
"""
from __future__ import annotations

import time
from typing import Callable

from domain.planning.states import StepState

from features.planning.application.dto.planning import (
    CancelPlanRequest,
)
from features.planning.application.mapping import (
    plan_to_record,
    record_to_plan,
)
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.use_cases.helpers import iso


class CancelPlanUseCase:
    def __init__(self, *, store: PlanStorePort, clock: Callable):
        self._store = store
        self._clock = clock

    def execute(self, request: CancelPlanRequest) -> dict:
        started = time.monotonic()
        plan_id = (request.plan_id or "").strip()

        if not plan_id:
            return self._deny(started, "معرّف الخطة مطلوب.")

        record = self._store.get(plan_id)
        if record is None:
            return self._deny(
                started, f"لا توجد خطة بالمعرّف {plan_id}."
            )

        now = self._clock()
        plan = record_to_plan(record, now)
        now_iso = iso(now)

        skipped = 0
        for step in plan.steps:
            if step.state in (
                StepState.PENDING,
                StepState.BLOCKED,
            ):
                step.transition(StepState.SKIPPED, now=now_iso)
                skipped += 1

        if plan.awaiting_step_id is not None:
            target = next(
                (
                    s
                    for s in plan.steps
                    if s.step_id == plan.awaiting_step_id
                ),
                None,
            )
            if target is not None and (
                target.state is StepState.SKIPPED
            ):
                plan.awaiting_step_id = None

        plan.updated_at = now_iso
        self._store.save(plan_to_record(plan, now))

        return {
            "ok": True,
            "action": "plan_cancel",
            "message": (
                f"أُلغيت الخطة {plan.plan_id} "
                f"({skipped} خطوات متخطاة)."
            ),
            "plan": plan_to_record(plan, now).to_dict(),
            "evidence": {},
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        return {
            "ok": False,
            "action": "plan_cancel",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
