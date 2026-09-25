"""list_scheduled_tasks use case: authorize -> list."""
from __future__ import annotations

import time

from features.scheduler.application.dto.scheduler import (
    ListTasksRequest,
)
from features.scheduler.application.ports.scheduler_authorization import (
    SchedulerAuthorizationPort,
)
from features.scheduler.application.ports.task_store import TaskStorePort


class ListTasksUseCase:
    """Application service for the list_scheduled_tasks tool."""

    def __init__(
        self,
        authorization: SchedulerAuthorizationPort,
        store: TaskStorePort,
    ):
        self._authorization = authorization
        self._store = store

    def execute(
        self,
        request: ListTasksRequest,
    ) -> dict:
        started = time.monotonic()

        if not self._authorization.can_list():
            return {
                "ok": False,
                "action": "list_scheduled_tasks",
                "message": (
                    "غير مصرَّح بعرض المهام المجدولة."
                ),
                "evidence": {},
                "duration": time.monotonic() - started,
            }

        tasks = self._store.load_tasks()

        if not request.include_done:
            tasks = [
                t for t in tasks if t.status != "done"
            ]

        return {
            "ok": True,
            "action": "list_scheduled_tasks",
            "message": f"عدد المهام: {len(tasks)}",
            "tasks": [t.to_dict() for t in tasks],
            "evidence": {},
            "duration": time.monotonic() - started,
        }
