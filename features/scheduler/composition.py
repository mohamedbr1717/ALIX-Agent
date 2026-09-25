"""Composition root for the scheduler feature."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from features.scheduler.application.use_cases.cancel_task import (
    CancelTaskUseCase,
)
from features.scheduler.application.use_cases.list_tasks import (
    ListTasksUseCase,
)
from features.scheduler.application.use_cases.schedule_task import (
    ScheduleTaskUseCase,
)
from features.scheduler.infrastructure.adapters.json_task_store import (
    JsonTaskStore,
)
from features.scheduler.infrastructure.adapters.policy_scheduler_authorization import (
    PolicySchedulerAuthorizationAdapter,
)
from features.scheduler.interfaces.controllers.scheduler_controller import (
    CancelTaskController,
    ListTasksController,
    ScheduleTaskController,
)


def build_task_store(
    path: Optional[Path] = None,
) -> JsonTaskStore:
    """Build the task store (shared by tools and the daemon)."""
    return JsonTaskStore(path)


def _build_parts(policy, path=None):
    authorization = PolicySchedulerAuthorizationAdapter(policy)
    store = build_task_store(path)
    return authorization, store


def build_schedule_task_controller(
    policy,
    path: Optional[Path] = None,
):
    """Build the schedule_task controller with default adapters."""
    authorization, store = _build_parts(policy, path)
    use_case = ScheduleTaskUseCase(authorization, store)
    return ScheduleTaskController(use_case)


def build_list_tasks_controller(
    policy,
    path: Optional[Path] = None,
):
    """Build the list_scheduled_tasks controller."""
    authorization, store = _build_parts(policy, path)
    use_case = ListTasksUseCase(authorization, store)
    return ListTasksController(use_case)


def build_cancel_task_controller(
    policy,
    path: Optional[Path] = None,
):
    """Build the cancel_scheduled_task controller."""
    authorization, store = _build_parts(policy, path)
    use_case = CancelTaskUseCase(authorization, store)
    return CancelTaskController(use_case)
