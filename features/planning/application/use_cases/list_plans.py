"""list_plans use case (backs plan_status without an id).

"Unfinished" = derived state in {pending, running,
awaiting_approval, blocked}: plans still needing execution or an
owner decision. Finished plans (done/failed/escalated/expired)
are listed only when explicitly requested.
"""
from __future__ import annotations

import time
from typing import Callable

from domain.planning.derivation import derive_plan_state
from domain.planning.states import PlanState

from features.planning.application.dto.planning import (
    ListPlansRequest,
)
from features.planning.application.mapping import record_to_plan
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)

_UNFINISHED = frozenset(
    {
        PlanState.PENDING,
        PlanState.RUNNING,
        PlanState.AWAITING_APPROVAL,
        PlanState.BLOCKED,
    }
)


class ListPlansUseCase:
    def __init__(self, *, store: PlanStorePort, clock: Callable):
        self._store = store
        self._clock = clock

    def execute(self, request: ListPlansRequest) -> dict:
        started = time.monotonic()
        now = self._clock()

        plans = []
        for record in self._store.list_all():
            plan = record_to_plan(record, now)
            state = derive_plan_state(plan, now)
            if (
                not request.include_finished
                and state not in _UNFINISHED
            ):
                continue
            entry = record.to_dict()
            entry["state"] = state.value
            plans.append(entry)

        return {
            "ok": True,
            "action": "plan_status",
            "message": f"{len(plans)} خطة.",
            "plans": plans,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
