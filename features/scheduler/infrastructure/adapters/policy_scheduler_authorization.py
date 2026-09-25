"""Policy-backed authorization for the scheduler slice."""
from __future__ import annotations

from typing import Any

from features.scheduler.application.ports.scheduler_authorization import (
    SchedulerAuthorizationPort,
)


class PolicySchedulerAuthorizationAdapter(
    SchedulerAuthorizationPort
):
    """Adapt the existing ALIX Policy to the scheduler port."""

    def __init__(self, policy: Any):
        self._policy = policy

    def can_schedule(self) -> bool:
        return bool(
            self._policy.tool_allowed("schedule_task")
        )

    def can_cancel(self) -> bool:
        return bool(
            self._policy.tool_allowed("cancel_scheduled_task")
        )

    def can_list(self) -> bool:
        return bool(
            self._policy.tool_allowed("list_scheduled_tasks")
        )
