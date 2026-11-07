"""Behavioral tests for the scheduler timezone convention.

The scheduler's single frame is Africa/Casablanca local time (the
same convention the calendar gateway and the planning read-back
verifier already use): naive ISO values are read as Casablanca
wall-clock, the future-gate compares in that frame, and cron
occurrences match Casablanca wall-clock fields. Before this fix the
scheduler read naive values in the HOST timezone — on the UTC VPS a
Casablanca time one minute in the past parsed as ~59 minutes in the
future and passed the gate (the 2026-11-05 past-time drift).

Expectations are computed from Casablanca now at run time, so the
tests are deterministic on any host timezone.
"""
from __future__ import annotations

import os
import time
import unittest
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo("Africa/Casablanca")
except Exception:  # tzdata unavailable (rare) — Morocco is UTC+1
    LOCAL_TZ = timezone(timedelta(hours=1))

from features.scheduler.application.dto.scheduler import (
    ScheduleTaskRequest,
)
from features.scheduler.application.use_cases.run_due_tasks import (
    RunDueTasksUseCase,
    _parse_iso,
)
from features.scheduler.application.use_cases.schedule_task import (
    ScheduleTaskUseCase,
)
from test_scheduler import AllowAuth, make_store


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def naive_iso(moment: datetime) -> str:
    """ISO string with no offset — how a local time is often written."""
    return moment.replace(tzinfo=None).isoformat(timespec="seconds")


class NoopExecutor:
    def execute_task(self, prompt, allow, **kwargs):
        return "done"


class TestNaiveAtTimes(unittest.TestCase):
    def make_uc(self, store):
        return ScheduleTaskUseCase(AllowAuth(), store)

    def test_naive_two_hours_ahead_accepted_in_local_frame(self):
        store = make_store()
        target = local_now() + timedelta(hours=2)

        result = self.make_uc(store).execute(
            ScheduleTaskRequest(
                name="once",
                prompt="ذكرني",
                kind="at",
                schedule=naive_iso(target),
            )
        )

        self.assertTrue(result["ok"], result["message"])
        stored = datetime.fromisoformat(result["task"]["next_run"])
        # The stored value is the intended Casablanca wall-clock time,
        # carrying Casablanca's offset — not the host's.
        expected = datetime.fromisoformat(
            naive_iso(target)
        ).replace(tzinfo=LOCAL_TZ)
        self.assertEqual(stored, expected)
        self.assertEqual(
            stored.utcoffset(), expected.utcoffset()
        )
        self.assertEqual(
            (stored.hour, stored.minute, stored.second),
            (expected.hour, expected.minute, expected.second),
        )

    def test_naive_one_minute_behind_rejected_by_future_gate(self):
        # Regression proof: this string is ~1 minute in the past in
        # Casablanca. Under the old host-tz reading on a UTC host it
        # landed ~59 minutes in the FUTURE and was wrongly accepted.
        store = make_store()
        behind = local_now() - timedelta(minutes=1)

        result = self.make_uc(store).execute(
            ScheduleTaskRequest(
                name="late",
                prompt="ذكرني",
                kind="at",
                schedule=naive_iso(behind),
            )
        )

        self.assertFalse(result["ok"])
        self.assertIn("المستقبل", result["message"])
        self.assertEqual(store.load_tasks(), [])


class TestAwareAtTimesUnchanged(unittest.TestCase):
    def test_aware_plus01_future_accepted_offset_preserved(self):
        store = make_store()
        plus_one = timezone(timedelta(hours=1))
        target = datetime.now(plus_one) + timedelta(hours=2)
        text = target.isoformat(timespec="seconds")
        self.assertTrue(text.endswith("+01:00"))

        result = ScheduleTaskUseCase(AllowAuth(), store).execute(
            ScheduleTaskRequest(
                name="once",
                prompt="ذكرني",
                kind="at",
                schedule=text,
            )
        )

        self.assertTrue(result["ok"], result["message"])
        # Aware values pass through exactly as before.
        self.assertEqual(result["task"]["next_run"], text)


class TestCronWallClock(unittest.TestCase):
    def test_daily_9am_is_casablanca_wall_clock(self):
        store = make_store()

        result = ScheduleTaskUseCase(AllowAuth(), store).execute(
            ScheduleTaskRequest(
                name="morning",
                prompt="لخص الأخبار",
                kind="cron",
                schedule="0 9 * * *",
                allow="read",
            )
        )

        self.assertTrue(result["ok"], result["message"])
        stored = datetime.fromisoformat(result["task"]["next_run"])
        self.assertEqual((stored.hour, stored.minute), (9, 0))
        self.assertEqual(
            stored.utcoffset(),
            stored.astimezone(LOCAL_TZ).utcoffset(),
        )
        # The 09:00 is Casablanca's: the same instant read in local
        # fields is still 09:00, and it lies in the future.
        self.assertEqual(
            stored.astimezone(LOCAL_TZ).hour, 9
        )
        self.assertGreater(stored, local_now())


class TestRunDueParsing(unittest.TestCase):
    def test_parse_iso_naive_yields_local_offset(self):
        parsed = _parse_iso("2026-09-26T08:00:00")

        expected = datetime(
            2026, 9, 26, 8, 0, tzinfo=LOCAL_TZ
        )
        self.assertEqual(parsed, expected)
        self.assertEqual(
            parsed.utcoffset(), expected.utcoffset()
        )

    def test_parse_iso_aware_unchanged(self):
        parsed = _parse_iso("2026-09-26T08:00:00+01:00")

        self.assertEqual(
            parsed.utcoffset(), timedelta(hours=1)
        )
        self.assertEqual((parsed.hour, parsed.minute), (8, 0))

    def test_default_clock_reports_local_time(self):
        uc = RunDueTasksUseCase(
            store=make_store(),
            executor=NoopExecutor(),
        )

        outcome = uc.execute()

        checked = datetime.fromisoformat(outcome["checked_at"])
        self.assertEqual(
            checked.utcoffset(),
            local_now().utcoffset(),
        )


@unittest.skipUnless(
    hasattr(time, "tzset"),
    "host-tz switching needs time.tzset (POSIX)",
)
class TestHostTimezoneIndependence(unittest.TestCase):
    """The convention must hold whatever the HOST timezone is.

    With Morocco at UTC+0 and a UTC host, the Casablanca frame and
    the host frame coincide, so the tests above cannot distinguish
    the fix from the old host-tz reading. Running the same checks
    under a foreign host tz (America/New_York, always behind
    Casablanca) is what proves the frame is pinned: under the old
    code the past-time gate wrongly ACCEPTS here, because a naive
    Casablanca time read as New York time lands hours in the future.
    """

    FOREIGN_TZ = "America/New_York"

    def setUp(self):
        self._saved_tz = os.environ.get("TZ")
        os.environ["TZ"] = self.FOREIGN_TZ
        time.tzset()

    def tearDown(self):
        if self._saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._saved_tz
        time.tzset()

    def test_gate_still_rejects_casablanca_past_under_foreign_host(self):
        store = make_store()
        behind = local_now() - timedelta(minutes=1)

        result = ScheduleTaskUseCase(AllowAuth(), store).execute(
            ScheduleTaskRequest(
                name="late",
                prompt="ذكرني",
                kind="at",
                schedule=naive_iso(behind),
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(store.load_tasks(), [])

    def test_naive_still_stored_with_casablanca_offset(self):
        store = make_store()
        target = local_now() + timedelta(hours=2)

        result = ScheduleTaskUseCase(AllowAuth(), store).execute(
            ScheduleTaskRequest(
                name="once",
                prompt="ذكرني",
                kind="at",
                schedule=naive_iso(target),
            )
        )

        self.assertTrue(result["ok"], result["message"])
        stored = datetime.fromisoformat(result["task"]["next_run"])
        self.assertEqual(
            stored.utcoffset(),
            target.utcoffset(),
        )
        # Same instant and wall clock, at storage (seconds) precision.
        self.assertEqual(
            stored, target.replace(microsecond=0)
        )

    def test_cron_still_casablanca_wall_clock_under_foreign_host(self):
        store = make_store()

        result = ScheduleTaskUseCase(AllowAuth(), store).execute(
            ScheduleTaskRequest(
                name="morning",
                prompt="لخص الأخبار",
                kind="cron",
                schedule="0 9 * * *",
                allow="read",
            )
        )

        self.assertTrue(result["ok"], result["message"])
        stored = datetime.fromisoformat(result["task"]["next_run"])
        local_view = stored.astimezone(LOCAL_TZ)
        self.assertEqual((local_view.hour, local_view.minute), (9, 0))


if __name__ == "__main__":
    unittest.main()
