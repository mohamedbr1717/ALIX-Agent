"""run_due_tasks use case: find due tasks, execute, advance state.

Pure orchestration over the store + executor ports. Time comes from
an injectable clock (tests use a fake clock).

Per active task:
- not yet due -> skip.
- due but later than max_lateness_hours (or catch_up is off) ->
  "missed": cron tasks get next_run recomputed, one-shot "at"
  tasks are closed as missed.
- due -> executor runs the prompt under the task's pre-authorized
  ceiling ("allow"). On success the task advances (cron: next_run
  moves forward; at: status "done"). On executor failure the task
  is marked "failed" and still advances, so a failing task can
  never hot-loop the daemon.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from domain.scheduling.cron import next_after
from features.scheduler.application.dto.scheduler import TaskRecord
from features.scheduler.application.ports.task_executor import (
    TaskExecutorPort,
)
from features.scheduler.application.ports.task_store import TaskStorePort


def _parse_iso(value: str) -> datetime:
    moment = datetime.fromisoformat(value)

    if moment.tzinfo is None:
        moment = moment.astimezone()

    return moment


class RunDueTasksUseCase:
    def __init__(
        self,
        store: TaskStorePort,
        executor: TaskExecutorPort,
        clock: Optional[Callable[[], datetime]] = None,
        audit_fn: Optional[
            Callable[[str, Dict[str, Any]], Any]
        ] = None,
    ):
        self._store = store
        self._executor = executor
        self._clock = (
            clock
            or (lambda: datetime.now().astimezone())
        )
        self._audit_fn = audit_fn

    # ------------------------------------------------------

    def _audit(self, event: str, data: dict) -> None:

        if self._audit_fn is None:
            return

        try:
            self._audit_fn(event, data)
        except Exception:
            pass

    # ------------------------------------------------------

    def execute(self) -> dict:
        started = time.monotonic()
        now = self._clock()

        tasks = self._store.load_tasks()
        ran: List[dict] = []
        missed: List[dict] = []
        failed: List[dict] = []
        changed = False

        for task in tasks:

            if task.status != "active":
                continue

            try:
                next_run = _parse_iso(task.next_run)
            except ValueError:
                continue

            if now < next_run:
                continue

            lateness = now - next_run
            too_late = lateness > timedelta(
                hours=task.max_lateness_hours
            )

            if too_late or not task.catch_up:
                self._mark_missed(
                    task, now, missed, reason=(
                        "too_late"
                        if too_late
                        else "catch_up_off"
                    ),
                )
                changed = True
                continue

            updated, result_text = self._run_one(
                task, now
            )
            entry = updated.to_dict()
            entry["result"] = result_text[:2000]

            if updated.status == "failed":
                failed.append(entry)
            else:
                ran.append(entry)

            changed = True

        if changed:
            # Rebuild the list preserving order, swapping in updates.
            by_id = {t.id: t for t in tasks}

            for entry in ran + missed + failed:
                rec = TaskRecord.from_dict(entry)
                by_id[rec.id] = rec

            self._store.save_tasks(
                [by_id[t.id] for t in tasks]
            )

        return {
            "ok": True,
            "action": "run_due_tasks",
            "checked_at": now.isoformat(timespec="seconds"),
            "ran": ran,
            "missed": missed,
            "failed": failed,
            "evidence": {},
            "duration": time.monotonic() - started,
        }

    # ------------------------------------------------------

    def _advance_cron(
        self,
        task: TaskRecord,
        now: datetime,
    ) -> str:
        return next_after(
            task.schedule, now
        ).isoformat(timespec="seconds")

    def _mark_missed(
        self,
        task: TaskRecord,
        now: datetime,
        missed: list,
        reason: str,
    ) -> None:
        self._audit(
            "task_missed",
            {
                "task_id": task.id,
                "name": task.name,
                "reason": reason,
            },
        )

        if task.kind == "cron":

            updated = TaskRecord(
                **{
                    **task.to_dict(),
                    "next_run": self._advance_cron(
                        task, now
                    ),
                }
            )

        else:

            updated = TaskRecord(
                **{**task.to_dict(), "status": "missed"}
            )

        missed.append(updated.to_dict())

    def _run_one(
        self,
        task: TaskRecord,
        now: datetime,
    ) -> tuple:
        """Run one task; return (updated_record, result_text)."""
        self._audit(
            "task_run_start",
            {"task_id": task.id, "name": task.name},
        )

        try:
            result_text = self._executor.execute_task(
                task.prompt,
                task.allow,
            )
            success = True
        except Exception as exc:
            result_text = f"❌ {exc}"
            success = False

        base = {
            **task.to_dict(),
            "last_run": now.isoformat(
                timespec="seconds"
            ),
            "run_count": task.run_count + 1,
        }

        if task.kind == "cron":
            base["next_run"] = self._advance_cron(
                task, now
            )
            base["status"] = (
                "active" if success else "failed"
            )
        else:
            base["status"] = (
                "done" if success else "failed"
            )

        self._audit(
            "task_run_end",
            {
                "task_id": task.id,
                "name": task.name,
                "status": base["status"],
                "result_chars": len(result_text),
            },
        )

        return TaskRecord.from_dict(base), result_text
