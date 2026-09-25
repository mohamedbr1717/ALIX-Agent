"""schedule_task use case: authorize -> validate -> persist."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone

from domain.scheduling.cron import next_after, parse_cron
from features.scheduler.application.dto.scheduler import (
    ALLOWED_CEILINGS,
    ScheduleTaskRequest,
    TaskRecord,
)
from features.scheduler.application.ports.scheduler_authorization import (
    SchedulerAuthorizationPort,
)
from features.scheduler.application.ports.task_store import TaskStorePort


def _now_iso() -> str:
    return (
        datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )


def _parse_at(value: str) -> datetime:
    """Parse an ISO datetime; naive values mean local time."""

    text = value.strip()

    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"صيغة التاريخ غير صالحة: {value!r} "
            "(استخدم ISO مثل 2026-09-26T08:00)"
        ) from exc

    if moment.tzinfo is None:
        moment = moment.astimezone()

    return moment


class ScheduleTaskUseCase:
    """Application service for the schedule_task tool."""

    def __init__(
        self,
        authorization: SchedulerAuthorizationPort,
        store: TaskStorePort,
    ):
        self._authorization = authorization
        self._store = store

    def execute(
        self,
        request: ScheduleTaskRequest,
    ) -> dict:
        started = time.monotonic()

        if not self._authorization.can_schedule():
            return self._deny(
                started,
                "غير مصرَّح بإنشاء مهام مجدولة.",
            )

        name = (request.name or "").strip()
        prompt = (request.prompt or "").strip()

        if not name:
            return self._deny(
                started, "اسم المهمة مطلوب."
            )

        if not prompt:
            return self._deny(
                started, "نص المهمة (prompt) مطلوب."
            )

        if len(prompt) > 4000:
            return self._deny(
                started,
                "نص المهمة طويل جدًا (الحد 4000 حرف).",
            )

        allow = (request.allow or "read").strip().lower()

        if allow not in ALLOWED_CEILINGS:
            return self._deny(
                started,
                "مستوى الصلاحية must be one of: "
                + ", ".join(sorted(ALLOWED_CEILINGS))
                + ". (destructive ممنوع في المهام المجدولة)",
            )

        kind = (request.kind or "").strip().lower()

        if kind not in ("cron", "at"):
            return self._deny(
                started,
                "النوع must be 'cron' أو 'at'.",
            )

        now = datetime.now().astimezone()

        try:

            if kind == "cron":
                parse_cron(request.schedule)
                first_run = next_after(
                    request.schedule, now
                )
            else:
                first_run = _parse_at(request.schedule)

                if first_run <= now:
                    return self._deny(
                        started,
                        "وقت التنفيذ يجب أن يكون في المستقبل.",
                    )

        except ValueError as exc:
            return self._deny(started, str(exc))
        except RuntimeError as exc:
            return self._deny(started, str(exc))

        try:
            max_lateness = float(
                request.max_lateness_hours
            )
        except (TypeError, ValueError):
            return self._deny(
                started,
                "max_lateness_hours يجب أن يكون رقمًا.",
            )

        if max_lateness < 0:
            return self._deny(
                started,
                "max_lateness_hours لا يمكن أن يكون سالبًا.",
            )

        task = TaskRecord(
            id=f"sch-{secrets.token_hex(4)}",
            name=name,
            prompt=prompt,
            kind=kind,
            schedule=request.schedule.strip(),
            next_run=first_run.isoformat(
                timespec="seconds"
            ),
            allow=allow,
            catch_up=bool(request.catch_up),
            max_lateness_hours=max_lateness,
            status="active",
            created_at=_now_iso(),
        )

        tasks = self._store.load_tasks()
        tasks.append(task)
        self._store.save_tasks(tasks)

        return {
            "ok": True,
            "action": "schedule_task",
            "message": (
                f"تمت جدولة '{name}' ({task.id}) — "
                f"التنفيذ التالي: {task.next_run}"
            ),
            "task": task.to_dict(),
            "evidence": {},
            "duration": time.monotonic() - started,
        }

    @staticmethod
    def _deny(started: float, message: str) -> dict:
        return {
            "ok": False,
            "action": "schedule_task",
            "message": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "evidence": {},
            "duration": time.monotonic() - started,
        }
