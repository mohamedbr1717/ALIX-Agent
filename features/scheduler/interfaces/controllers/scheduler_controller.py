"""Controllers (interface adapters) for the scheduler tools."""
from __future__ import annotations

from features.scheduler.application.dto.scheduler import (
    CancelTaskRequest,
    ListTasksRequest,
    ScheduleTaskRequest,
)
from features.scheduler.application.use_cases.cancel_task import (
    CancelTaskUseCase,
)
from features.scheduler.application.use_cases.list_tasks import (
    ListTasksUseCase,
)
from features.scheduler.application.use_cases.schedule_task import (
    ScheduleTaskUseCase,
)


class ScheduleTaskController:
    """Translate raw tool arguments into a schedule request."""

    def __init__(self, use_case: ScheduleTaskUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}

        return self._use_case.execute(
            ScheduleTaskRequest(
                name=arguments.get("name", ""),
                prompt=arguments.get("prompt", ""),
                kind=arguments.get("kind", ""),
                schedule=arguments.get("schedule", ""),
                allow=arguments.get("allow", "read"),
                catch_up=arguments.get("catch_up", True),
                max_lateness_hours=arguments.get(
                    "max_lateness_hours", 24.0
                ),
            )
        )


class ListTasksController:
    def __init__(self, use_case: ListTasksUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}

        return self._use_case.execute(
            ListTasksRequest(
                include_done=bool(
                    arguments.get("include_done", False)
                ),
            )
        )


class CancelTaskController:
    def __init__(self, use_case: CancelTaskUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}

        return self._use_case.execute(
            CancelTaskRequest(
                task_id=arguments.get("task_id", ""),
            )
        )
