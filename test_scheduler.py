"""Behavioral tests for the native scheduler.

Covers: cron parsing/next-occurrence (domain), the schedule/list/
cancel tools (slice), due-task execution with a fake clock,
scheduled-mode policy gates (fail-closed), and store robustness.
No real LLM, no network, no touching live state.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from domain.scheduling.cron import (
    next_after,
    parse_cron,
)
from features.scheduler.application.dto.scheduler import (
    CancelTaskRequest,
    ListTasksRequest,
    ScheduleTaskRequest,
    TaskRecord,
)
from features.scheduler.application.use_cases.cancel_task import (
    CancelTaskUseCase,
)
from features.scheduler.application.use_cases.list_tasks import (
    ListTasksUseCase,
)
from features.scheduler.application.use_cases.run_due_tasks import (
    RunDueTasksUseCase,
)
from features.scheduler.application.use_cases.schedule_task import (
    ScheduleTaskUseCase,
)
from features.scheduler.infrastructure.adapters.json_task_store import (
    JsonTaskStore,
)
from test_agent_behavior import make_agent


# ============================================================
# Helpers
# ============================================================

LOCAL = datetime.now().astimezone().tzinfo


def aware(
    year, month, day, hour=0, minute=0
) -> datetime:
    return datetime(
        year, month, day, hour, minute, tzinfo=LOCAL
    )


class AllowAuth:
    def can_schedule(self):
        return True

    def can_cancel(self):
        return True

    def can_list(self):
        return True


class DenyAuth:
    def can_schedule(self):
        return False

    def can_cancel(self):
        return False

    def can_list(self):
        return False


class StubExecutor:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def execute_task(self, prompt, allow):
        self.calls.append(
            {"prompt": prompt, "allow": allow}
        )

        if self.fail:
            raise RuntimeError("executor boom")

        return f"done:{prompt[:20]}"


def make_store():
    tmp = tempfile.mkdtemp()
    return JsonTaskStore(
        Path(tmp) / "tasks.json"
    )


def seed_task(store, **over):
    record = TaskRecord(
        id=over.get("id", "sch-test01"),
        name=over.get("name", "t"),
        prompt=over.get("prompt", "do it"),
        kind=over.get("kind", "cron"),
        schedule=over.get("schedule", "0 8 * * *"),
        next_run=over.get(
            "next_run",
            aware(2026, 9, 26, 8, 0).isoformat(),
        ),
        allow=over.get("allow", "read"),
        catch_up=over.get("catch_up", True),
        max_lateness_hours=over.get(
            "max_lateness_hours", 24.0
        ),
        status=over.get("status", "active"),
        created_at=aware(2026, 9, 25, 12, 0).isoformat(),
    )
    store.save_tasks(store.load_tasks() + [record])
    return record


# ============================================================
# Cron domain
# ============================================================

class TestCronDomain(unittest.TestCase):
    def test_parse_every_day_8am(self):
        spec = parse_cron("0 8 * * *")
        self.assertEqual(spec.minutes, frozenset({0}))
        self.assertEqual(spec.hours, frozenset({8}))

    def test_parse_step_and_list(self):
        spec = parse_cron("*/15 9-17 * * 1,3,5")
        self.assertIn(0, spec.minutes)
        self.assertIn(30, spec.minutes)
        self.assertIn(9, spec.hours)
        self.assertIn(17, spec.hours)
        self.assertNotIn(18, spec.hours)
        self.assertEqual(
            spec.weekdays, frozenset({1, 3, 5})
        )

    def test_parse_rejects_bad_count(self):
        with self.assertRaises(ValueError):
            parse_cron("0 8 * *")

    def test_parse_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_cron("99 8 * * *")

    def test_parse_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_cron("nope * * * *")

    def test_next_after_daily(self):
        # Mon 2026-09-28 10:00 -> Tue 2026-09-29 08:00.
        nxt = next_after(
            "0 8 * * *",
            aware(2026, 9, 28, 10, 0),
        )
        self.assertEqual(
            nxt, aware(2026, 9, 29, 8, 0)
        )

    def test_next_after_weekly(self):
        # Monday 10:00 -> next Monday 09:00.
        nxt = next_after(
            "0 9 * * 1",
            aware(2026, 9, 28, 10, 0),
        )
        self.assertEqual(
            nxt, aware(2026, 10, 5, 9, 0)
        )

    def test_next_after_step_minutes(self):
        nxt = next_after(
            "*/15 * * * *",
            aware(2026, 9, 28, 10, 7),
        )
        self.assertEqual(
            nxt, aware(2026, 9, 28, 10, 15)
        )

    def test_next_after_dom_or_dow(self):
        # 1st of month OR Sunday -> 2026-10-01 (Thursday).
        nxt = next_after(
            "0 0 1 * 0",
            aware(2026, 9, 28, 10, 0),
        )
        self.assertEqual(
            nxt, aware(2026, 10, 1, 0, 0)
        )

    def test_next_after_strictly_after(self):
        at_eight = aware(2026, 9, 29, 8, 0)
        nxt = next_after("0 8 * * *", at_eight)
        self.assertEqual(
            nxt, aware(2026, 9, 30, 8, 0)
        )


# ============================================================
# schedule/list/cancel tools
# ============================================================

class TestScheduleTool(unittest.TestCase):
    def make_uc(self, auth=None, store=None):
        return (
            ScheduleTaskUseCase(
                auth or AllowAuth(),
                store or make_store(),
            ),
            store or make_store(),
        )

    def test_schedule_cron_ok(self):
        store = make_store()
        uc = ScheduleTaskUseCase(AllowAuth(), store)

        result = uc.execute(
            ScheduleTaskRequest(
                name="briefing",
                prompt="لخص الأخبار",
                kind="cron",
                schedule="0 8 * * *",
                allow="read",
            )
        )

        self.assertTrue(result["ok"])
        task = result["task"]
        self.assertTrue(task["id"].startswith("sch-"))
        self.assertEqual(task["status"], "active")
        # next_run is a future 08:00.
        nxt = datetime.fromisoformat(task["next_run"])
        self.assertEqual((nxt.hour, nxt.minute), (8, 0))
        self.assertGreater(
            nxt, datetime.now().astimezone()
        )
        self.assertEqual(len(store.load_tasks()), 1)

    def test_schedule_at_future_ok(self):
        store = make_store()
        uc = ScheduleTaskUseCase(AllowAuth(), store)
        future = (
            datetime.now().astimezone()
            + timedelta(hours=2)
        ).isoformat(timespec="seconds")

        result = uc.execute(
            ScheduleTaskRequest(
                name="once",
                prompt="ذكرني",
                kind="at",
                schedule=future,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["task"]["next_run"], future
        )

    def test_schedule_at_past_denied(self):
        uc = ScheduleTaskUseCase(
            AllowAuth(), make_store()
        )
        past = (
            datetime.now().astimezone()
            - timedelta(hours=1)
        ).isoformat()

        result = uc.execute(
            ScheduleTaskRequest(
                name="x", prompt="y",
                kind="at", schedule=past,
            )
        )

        self.assertFalse(result["ok"])

    def test_schedule_bad_cron_denied(self):
        uc = ScheduleTaskUseCase(
            AllowAuth(), make_store()
        )

        result = uc.execute(
            ScheduleTaskRequest(
                name="x", prompt="y",
                kind="cron", schedule="99 99 * * *",
            )
        )

        self.assertFalse(result["ok"])

    def test_schedule_destructive_ceiling_denied(self):
        uc = ScheduleTaskUseCase(
            AllowAuth(), make_store()
        )

        result = uc.execute(
            ScheduleTaskRequest(
                name="x", prompt="y",
                kind="cron", schedule="0 8 * * *",
                allow="destructive",
            )
        )

        self.assertFalse(result["ok"])
        self.assertIn("destructive", result["message"])

    def test_schedule_empty_prompt_denied(self):
        uc = ScheduleTaskUseCase(
            AllowAuth(), make_store()
        )

        result = uc.execute(
            ScheduleTaskRequest(
                name="x", prompt="  ",
                kind="cron", schedule="0 8 * * *",
            )
        )

        self.assertFalse(result["ok"])

    def test_schedule_auth_denied(self):
        uc = ScheduleTaskUseCase(
            DenyAuth(), make_store()
        )

        result = uc.execute(
            ScheduleTaskRequest(
                name="x", prompt="y",
                kind="cron", schedule="0 8 * * *",
            )
        )

        self.assertFalse(result["ok"])

    def test_ids_are_unique(self):
        store = make_store()
        uc = ScheduleTaskUseCase(AllowAuth(), store)
        ids = set()

        for i in range(5):
            result = uc.execute(
                ScheduleTaskRequest(
                    name=f"t{i}", prompt="y",
                    kind="cron", schedule="0 8 * * *",
                )
            )
            ids.add(result["task"]["id"])

        self.assertEqual(len(ids), 5)


class TestListCancelTools(unittest.TestCase):
    def test_list_and_cancel(self):
        store = make_store()
        seed_task(store, id="sch-a", name="a")
        seed_task(
            store, id="sch-b", name="b",
            status="done",
        )

        listed = ListTasksUseCase(
            AllowAuth(), store
        ).execute(ListTasksRequest())

        self.assertTrue(listed["ok"])
        # done tasks hidden by default.
        self.assertEqual(len(listed["tasks"]), 1)

        listed_all = ListTasksUseCase(
            AllowAuth(), store
        ).execute(ListTasksRequest(include_done=True))
        self.assertEqual(len(listed_all["tasks"]), 2)

        cancelled = CancelTaskUseCase(
            AllowAuth(), store
        ).execute(CancelTaskRequest(task_id="sch-a"))
        self.assertTrue(cancelled["ok"])
        self.assertEqual(len(store.load_tasks()), 1)

    def test_cancel_unknown_denied(self):
        result = CancelTaskUseCase(
            AllowAuth(), make_store()
        ).execute(CancelTaskRequest(task_id="sch-nope"))
        self.assertFalse(result["ok"])

    def test_list_auth_denied(self):
        result = ListTasksUseCase(
            DenyAuth(), make_store()
        ).execute(ListTasksRequest())
        self.assertFalse(result["ok"])


# ============================================================
# Due-task execution
# ============================================================

class TestRunDueTasks(unittest.TestCase):
    def run_with_clock(
        self, store, clock, executor=None
    ):
        uc = RunDueTasksUseCase(
            store=store,
            executor=executor or StubExecutor(),
            clock=clock,
        )
        return uc.execute()

    def test_due_cron_runs_once_and_advances(self):
        store = make_store()
        seed_task(
            store,
            schedule="0 8 * * *",
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
        )
        executor = StubExecutor()

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 9, 29, 8, 1),
            executor,
        )

        self.assertEqual(len(outcome["ran"]), 1)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(
            executor.calls[0]["prompt"], "do it"
        )
        self.assertEqual(
            executor.calls[0]["allow"], "read"
        )

        tasks = store.load_tasks()
        self.assertEqual(tasks[0].run_count, 1)
        # Next run moved to the following day 08:00.
        self.assertEqual(
            datetime.fromisoformat(tasks[0].next_run),
            aware(2026, 9, 30, 8, 0),
        )

    def test_not_due_skipped(self):
        store = make_store()
        seed_task(
            store,
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
        )
        executor = StubExecutor()

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 9, 29, 7, 59),
            executor,
        )

        self.assertEqual(outcome["ran"], [])
        self.assertEqual(executor.calls, [])

    def test_one_shot_at_becomes_done(self):
        store = make_store()
        seed_task(
            store,
            kind="at",
            schedule="2026-09-29T08:00:00",
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
        )

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 9, 29, 8, 5),
        )

        self.assertEqual(len(outcome["ran"]), 1)
        self.assertEqual(
            store.load_tasks()[0].status, "done"
        )

    def test_too_late_cron_missed_and_rescheduled(self):
        store = make_store()
        seed_task(
            store,
            schedule="0 8 * * *",
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
            max_lateness_hours=24.0,
        )
        executor = StubExecutor()

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 10, 2, 12, 0),
            executor,
        )

        # 3 days late > 24h: not executed.
        self.assertEqual(outcome["ran"], [])
        self.assertEqual(len(outcome["missed"]), 1)
        self.assertEqual(executor.calls, [])
        # ...but the cron schedule continues.
        tasks = store.load_tasks()
        self.assertEqual(tasks[0].status, "active")
        self.assertGreater(
            datetime.fromisoformat(tasks[0].next_run),
            aware(2026, 10, 2, 12, 0),
        )

    def test_too_late_at_marked_missed(self):
        store = make_store()
        seed_task(
            store,
            kind="at",
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
            max_lateness_hours=1.0,
        )

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 9, 29, 12, 0),
        )

        self.assertEqual(len(outcome["missed"]), 1)
        self.assertEqual(
            store.load_tasks()[0].status, "missed"
        )

    def test_catch_up_off_skips_stale(self):
        store = make_store()
        seed_task(
            store,
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
            catch_up=False,
            max_lateness_hours=24.0,
        )
        executor = StubExecutor()

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 9, 29, 8, 30),
            executor,
        )

        self.assertEqual(outcome["ran"], [])
        self.assertEqual(len(outcome["missed"]), 1)
        self.assertEqual(executor.calls, [])

    def test_executor_failure_marks_failed_no_hotloop(self):
        store = make_store()
        seed_task(
            store,
            schedule="0 8 * * *",
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
        )
        executor = StubExecutor(fail=True)

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 9, 29, 8, 1),
            executor,
        )

        self.assertEqual(len(outcome["failed"]), 1)
        tasks = store.load_tasks()
        self.assertEqual(tasks[0].status, "failed")
        # Advanced past now: the next tick won't retry it.
        self.assertGreater(
            datetime.fromisoformat(tasks[0].next_run),
            aware(2026, 9, 29, 8, 1),
        )

    def test_paused_task_skipped(self):
        store = make_store()
        seed_task(
            store,
            status="paused",
            next_run=aware(
                2026, 9, 29, 8, 0
            ).isoformat(),
        )
        executor = StubExecutor()

        outcome = self.run_with_clock(
            store,
            lambda: aware(2026, 9, 29, 9, 0),
            executor,
        )

        self.assertEqual(outcome["ran"], [])
        self.assertEqual(executor.calls, [])


# ============================================================
# Scheduled-mode policy gates
# ============================================================

class TestScheduledPolicy(unittest.TestCase):
    def make_scheduled_agent(self, allow):
        tmp = tempfile.mkdtemp()
        agent = make_agent(tmp)
        agent.audit = mock.Mock()
        agent.policy.scheduled_mode = True
        agent.policy.scheduled_allow = allow
        return agent

    def test_destructive_never_permitted(self):
        agent = self.make_scheduled_agent("execute")
        self.assertFalse(
            agent.policy.scheduled_tool_permitted(
                "delete_file"
            )
        )

    def test_ceiling_enforced(self):
        agent = self.make_scheduled_agent("write")
        self.assertTrue(
            agent.policy.scheduled_tool_permitted(
                "write_file"
            )
        )
        self.assertFalse(
            agent.policy.scheduled_tool_permitted(
                "run_python"
            )
        )

    def test_read_ceiling(self):
        agent = self.make_scheduled_agent("read")
        self.assertTrue(
            agent.policy.scheduled_tool_permitted(
                "web_search"
            )
        )
        self.assertFalse(
            agent.policy.scheduled_tool_permitted(
                "write_file"
            )
        )

    def test_control_plane_denied_in_scheduled_mode(self):
        agent = self.make_scheduled_agent("execute")
        self.assertFalse(
            agent.policy.tool_allowed("schedule_task")
        )
        self.assertFalse(
            agent.policy.tool_allowed(
                "cancel_scheduled_task"
            )
        )

    def test_control_plane_allowed_interactively(self):
        tmp = tempfile.mkdtemp()
        agent = make_agent(tmp)
        self.assertTrue(
            agent.policy.tool_allowed("schedule_task")
        )

    def test_confirm_tool_denies_without_prompting(self):
        agent = self.make_scheduled_agent("read")

        with mock.patch(
            "builtins.input",
            side_effect=AssertionError(
                "must not prompt"
            ),
        ):
            self.assertFalse(
                agent.confirm_tool(
                    "delete_file",
                    {"path": "x"},
                )
            )
            self.assertFalse(
                agent.confirm_tool(
                    "write_file",
                    {"path": "x", "content": "y"},
                )
            )

        denied = [
            c.args[0]
            for c in agent.audit.call_args_list
        ]
        self.assertIn("scheduled_tool_denied", denied)

    def test_confirm_tool_allows_within_ceiling(self):
        agent = self.make_scheduled_agent("write")

        with mock.patch(
            "builtins.input",
            side_effect=AssertionError(
                "must not prompt"
            ),
        ):
            self.assertTrue(
                agent.confirm_tool(
                    "write_file",
                    {"path": "x", "content": "y"},
                )
            )


# ============================================================
# Store robustness
# ============================================================

class TestJsonTaskStore(unittest.TestCase):
    def test_round_trip(self):
        store = make_store()
        record = seed_task(store, id="sch-rt")
        loaded = store.load_tasks()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "sch-rt")
        self.assertEqual(
            loaded[0].to_dict(), record.to_dict()
        )

    def test_missing_file_is_empty(self):
        store = make_store()
        self.assertEqual(store.load_tasks(), [])

    def test_corrupt_file_is_empty_no_crash(self):
        store = make_store()
        store.path.write_text(
            "{not json", encoding="utf-8"
        )
        self.assertEqual(store.load_tasks(), [])

    def test_write_is_atomic(self):
        store = make_store()
        seed_task(store)
        raw = store.path.read_text(encoding="utf-8")
        # Valid JSON array on disk, never partial.
        import json

        data = json.loads(raw)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
