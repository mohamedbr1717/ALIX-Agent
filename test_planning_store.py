"""Decision 1 — plan store + crash semantics (spec §3.2 / §3.3).

Record roundtrips through JsonPlanStore, atomic-write crash
safety (a failed write leaves the previous file byte-identical),
tolerant reads, and startup recovery: an interrupted step is
BLOCKED with an unknown outcome — never re-dispatched.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from domain.planning.states import BlockedReason, StepState

from features.planning.application.dto.planning import (
    GetPlanRequest,
    PlanRecord,
    PlanStepRecord,
    PriorActionRecord,
)
from features.planning.application.use_cases.get_plan import (
    GetPlanUseCase,
)
from features.planning.application.use_cases.helpers import (
    system_clock,
)
from features.planning.application.use_cases.recover_plans import (
    RecoverPlansUseCase,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def fixed_clock():
    return NOW


def sample_record(plan_id="p_20261027T120000_ab12", **overrides):
    record = PlanRecord(
        plan_id=plan_id,
        goal="هدف تجريبي بأحرف عربية",
        origin="interactive",
        steps=(
            PlanStepRecord(
                step_id="s1",
                intent="أولى",
                tool="read_file",
                args={"path": "x"},
                state="succeeded",
                idempotency_key=f"{plan_id}:s1",
                result_ref="تمت القراءة",
                created_at="2026-10-27T12:00:00+00:00",
                updated_at="2026-10-27T12:00:00+00:00",
            ),
            PlanStepRecord(
                step_id="s2",
                intent="ثانية",
                tool="calendar_delete",
                args={"event_id": "42"},
                state="pending",
                depth=0,
                idempotency_key=f"{plan_id}:s2",
                verify={"mode": "readback"},
                compensate={"tool": "calendar_add"},
                created_at="2026-10-27T12:00:00+00:00",
                updated_at="2026-10-27T12:00:00+00:00",
            ),
            PlanStepRecord(
                step_id="s2.1",
                intent="فرعية",
                tool="read_file",
                args={},
                state="pending",
                depth=1,
                parent_step_id="s2",
                idempotency_key=f"{plan_id}:s2.1",
                created_at="2026-10-27T12:00:00+00:00",
                updated_at="2026-10-27T12:00:00+00:00",
            ),
        ),
        prior_actions=(
            PriorActionRecord(
                tool="list_files",
                args_hash="deadbeef",
                result_ref="3 ملفات",
            ),
        ),
        replans_used=1,
        replans_max=2,
        created_at="2026-10-27T12:00:00+00:00",
        updated_at="2026-10-27T12:00:00+00:00",
        expires_at="2026-10-28T12:00:00+00:00",
        state="pending",
    )
    for key, value in overrides.items():
        object.__setattr__(record, key, value)
    return record


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "plans.json"
        self.store = JsonPlanStore(self.path)


class TestRoundtrip(StoreCase):
    def test_full_record_roundtrip(self):
        record = sample_record()
        self.store.save(record)

        loaded = self.store.get(record.plan_id)
        self.assertEqual(loaded, record)
        # Reserved fields cross verbatim, uninterpreted.
        self.assertEqual(
            loaded.steps[1].verify, {"mode": "readback"}
        )
        self.assertEqual(
            loaded.steps[1].compensate,
            {"tool": "calendar_add"},
        )
        self.assertEqual(
            loaded.steps[2].parent_step_id, "s2"
        )
        self.assertEqual(loaded.replans_used, 1)

    def test_save_upserts_by_plan_id(self):
        self.store.save(sample_record())
        updated = sample_record(replans_used=2)
        self.store.save(updated)
        all_records = self.store.list_all()
        self.assertEqual(len(all_records), 1)
        self.assertEqual(all_records[0].replans_used, 2)

    def test_multiple_plans_listed(self):
        self.store.save(sample_record("p_a"))
        self.store.save(sample_record("p_b"))
        self.assertEqual(
            {r.plan_id for r in self.store.list_all()},
            {"p_a", "p_b"},
        )
        self.assertIsNone(self.store.get("p_missing"))


class TestAtomicCrashSafety(StoreCase):
    def test_replace_failure_keeps_original_bytes(self):
        self.store.save(sample_record())
        before = self.path.read_bytes()

        with mock.patch(
            "os.replace", side_effect=OSError("crash")
        ):
            with self.assertRaises(OSError):
                self.store.save(sample_record("p_other"))

        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(
            self.store.get("p_20261027T120000_ab12"),
            sample_record(),
        )
        leftovers = list(
            Path(self._tmp.name).glob(".plans-*.tmp")
        )
        self.assertEqual(leftovers, [])

    def test_mid_write_failure_keeps_original_bytes(self):
        self.store.save(sample_record())
        before = self.path.read_bytes()

        real_fdopen = os.fdopen

        class ExplodingWriter:
            def __init__(self, fh):
                self._fh = fh

            def write(self, data):
                self._fh.write(data[:10])
                raise OSError("disk died mid-write")

            def flush(self):
                pass

            def fileno(self):
                return self._fh.fileno()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._fh.close()
                return False

        def fake_fdopen(fd, *a, **kw):
            return ExplodingWriter(real_fdopen(fd, *a, **kw))

        with mock.patch("os.fdopen", side_effect=fake_fdopen):
            with self.assertRaises(OSError):
                self.store.save(sample_record("p_other"))

        self.assertEqual(self.path.read_bytes(), before)
        leftovers = list(
            Path(self._tmp.name).glob(".plans-*.tmp")
        )
        self.assertEqual(leftovers, [])


class TestTolerantReads(StoreCase):
    def test_missing_file_reads_empty(self):
        self.assertEqual(self.store.list_all(), [])
        self.assertIsNone(self.store.get("p_x"))

    def test_corrupt_json_reads_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.list_all(), [])

    def test_non_list_reads_empty(self):
        self.path.write_text('{"plan_id": "p"}', encoding="utf-8")
        self.assertEqual(self.store.list_all(), [])

    def test_one_bad_item_skipped_others_kept(self):
        good = sample_record("p_good")
        payload = [{"goal": "no id here"}, good.to_dict()]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = self.store.list_all()
        self.assertEqual([r.plan_id for r in loaded], ["p_good"])


class CountingNotifier:
    def __init__(self):
        self.recovered_calls = []

    def created(self, plan, approval_steps):
        pass

    def decomposed(self, plan, failed_step, new_step_ids):
        pass

    def escalated(self, plan, failed_step, reason):
        pass

    def finished(self, plan):
        pass

    def recovered(self, plans):
        self.recovered_calls.append(list(plans))


class TestCrashRecovery(StoreCase):
    def _recover(self, notifier=None):
        return RecoverPlansUseCase(
            store=self.store,
            clock=fixed_clock,
            notifier=notifier,
        )

    def test_running_step_becomes_blocked_unknown_outcome(self):
        record = sample_record()
        running = PlanStepRecord(
            step_id="s9",
            intent="جارية",
            tool="whatsapp_send",
            args={"to": "x"},
            state="running",
            attempts=1,
            idempotency_key=f"{record.plan_id}:s9",
        )
        object.__setattr__(
            record, "steps", record.steps + (running,)
        )
        self.store.save(record)

        affected = self._recover().execute()

        self.assertEqual(len(affected), 1)
        step = affected[0].step("s9")
        self.assertIs(step.state, StepState.BLOCKED)
        self.assertIs(
            step.blocked_reason,
            BlockedReason.INTERRUPTED_UNKNOWN_OUTCOME,
        )
        self.assertTrue(step.outcome_unknown)

        # Persisted, not just in memory.
        reloaded = self.store.get(record.plan_id)
        self.assertEqual(reloaded.steps[-1].state, "blocked")
        self.assertEqual(
            reloaded.steps[-1].blocked_reason,
            "interrupted_unknown_outcome",
        )
        self.assertTrue(reloaded.steps[-1].outcome_unknown)

    def test_awaiting_pending_step_becomes_approval_interrupted(
        self,
    ):
        record = sample_record(awaiting_step_id="s2")
        self.store.save(record)

        affected = self._recover().execute()

        self.assertEqual(len(affected), 1)
        plan = affected[0]
        step = plan.step("s2")
        self.assertIs(step.state, StepState.BLOCKED)
        self.assertIs(
            step.blocked_reason,
            BlockedReason.APPROVAL_INTERRUPTED,
        )
        self.assertFalse(step.outcome_unknown)
        self.assertIsNone(plan.awaiting_step_id)

    def test_one_combined_notification_for_all_affected(self):
        notifier = CountingNotifier()
        for pid in ("p_a", "p_b"):
            record = sample_record(pid)
            running = PlanStepRecord(
                step_id="s9",
                intent="جارية",
                tool="read_file",
                args={},
                state="running",
                idempotency_key=f"{pid}:s9",
            )
            object.__setattr__(
                record, "steps", record.steps + (running,)
            )
            self.store.save(record)

        affected = self._recover(notifier).execute()

        self.assertEqual(len(affected), 2)
        self.assertEqual(len(notifier.recovered_calls), 1)
        self.assertEqual(len(notifier.recovered_calls[0]), 2)

    def test_clean_store_recovers_nothing_and_notifies_nothing(
        self,
    ):
        notifier = CountingNotifier()
        self.store.save(sample_record())
        affected = self._recover(notifier).execute()
        self.assertEqual(affected, [])
        self.assertEqual(notifier.recovered_calls, [])

    def test_stored_state_string_is_not_trusted(self):
        # A record claiming "done" while its steps are pending:
        # the derivation recomputed on load wins (spec §2.5).
        record = sample_record(state="done")
        self.store.save(record)
        result = GetPlanUseCase(
            store=self.store, clock=fixed_clock
        ).execute(GetPlanRequest(plan_id=record.plan_id))
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "pending")


if __name__ == "__main__":
    unittest.main()
