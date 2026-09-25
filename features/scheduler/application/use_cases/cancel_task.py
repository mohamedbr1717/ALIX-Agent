"""cancel_scheduled_task use case: authorize -> remove."""
from __future__ import annotations

import time

from features.scheduler.application.dto.scheduler import (
    CancelTaskRequest,
)
from features.scheduler.application.ports.scheduler_authorization import (
    SchedulerAuthorizationPort,
)
from features.scheduler.application.ports.task_store import TaskStorePort


class CancelTaskUseCase:
    """Application service for the cancel_scheduled_task tool."""

    def __init__(
        self,
        authorization: SchedulerAuthorizationPort,
        store: TaskStorePort,
    ):
        self._authorization = authorization
        self._store = store

    def execute(
        self,
        request: CancelTaskRequest,
    ) -> dict:
        started = time.monotonic()

        if not self._authorization.can_cancel():
            return self._deny(
                started,
                "غير مصرَّح بإلغاء المهام المجدولة.",
            )

        task_id = (request.task_id or "").strip()

        if not task_id:
            return self._deny(
                started, "معرّف المهمة مطلوب."
            )

        tasks = self._store.load_tasks()
        remaining = [
            t for t in tasks if t.id != task_id
        ]

        if len(remaining) == len(tasks):
            return self._deny(
                started,
                f"لا توجد مهمة بالمعرّف {task_id}.",
            )

        self._store.save_tasks(remaining)

        return {
            "ok": True,
            "action": "cancel_scheduled_task",
            "message": f"تم إلغاء المهمة {task_id}.",
            "evidence": {},
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        return {
            "ok": False,
            "action": "cancel_scheduled_task",
            "message": message,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
