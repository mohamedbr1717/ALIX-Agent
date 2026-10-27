"""get_plan use case (backs the plan_status tool, single plan)."""
from __future__ import annotations

import time
from typing import Callable

from domain.planning.derivation import derive_plan_state

from features.planning.application.dto.planning import (
    GetPlanRequest,
)
from features.planning.application.mapping import record_to_plan
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)


class GetPlanUseCase:
    def __init__(self, *, store: PlanStorePort, clock: Callable):
        self._store = store
        self._clock = clock

    def execute(self, request: GetPlanRequest) -> dict:
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
        state = derive_plan_state(plan, now).value

        return {
            "ok": True,
            "action": "plan_status",
            "message": (
                f"الخطة {plan.plan_id}: {state} — "
                f"{len(plan.steps)} خطوات."
            ),
            "plan": record.to_dict(),
            "state": state,
            "evidence": {},
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        return {
            "ok": False,
            "action": "plan_status",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
