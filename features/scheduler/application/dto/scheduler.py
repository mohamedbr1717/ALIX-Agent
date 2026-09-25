"""DTOs for the scheduler slice."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


#: Permission ceilings a scheduled task may request. "destructive"
#: is deliberately absent: unattended destructive runs are never
#: authorized (fail-closed).
ALLOWED_CEILINGS = frozenset({"read", "write", "execute"})


@dataclass(frozen=True)
class ScheduleTaskRequest:
    name: str
    prompt: str
    kind: str  # "cron" | "at"
    schedule: str  # cron expression | ISO datetime
    allow: str = "read"
    catch_up: bool = True
    max_lateness_hours: float = 24.0


@dataclass(frozen=True)
class ListTasksRequest:
    include_done: bool = False


@dataclass(frozen=True)
class CancelTaskRequest:
    task_id: str


@dataclass(frozen=True)
class TaskRecord:
    """The persisted shape of one scheduled task."""

    id: str
    name: str
    prompt: str
    kind: str
    schedule: str
    next_run: str  # ISO datetime with offset
    allow: str
    catch_up: bool
    max_lateness_hours: float
    status: str  # "active" | "paused" | "done"
    created_at: str
    last_run: Optional[str] = None
    run_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "kind": self.kind,
            "schedule": self.schedule,
            "next_run": self.next_run,
            "allow": self.allow,
            "catch_up": self.catch_up,
            "max_lateness_hours": self.max_lateness_hours,
            "status": self.status,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
        }

    @staticmethod
    def from_dict(data: dict) -> "TaskRecord":
        return TaskRecord(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            prompt=str(data.get("prompt", "")),
            kind=str(data.get("kind", "")),
            schedule=str(data.get("schedule", "")),
            next_run=str(data.get("next_run", "")),
            allow=str(data.get("allow", "read")),
            catch_up=bool(data.get("catch_up", True)),
            max_lateness_hours=float(
                data.get("max_lateness_hours", 24.0)
            ),
            status=str(data.get("status", "active")),
            created_at=str(data.get("created_at", "")),
            last_run=data.get("last_run"),
            run_count=int(data.get("run_count", 0)),
        )
