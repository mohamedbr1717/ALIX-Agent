"""Decision 2 — ReadBackVerifier behavioral tests.

The verifier distrusts the tool result's ``ok``: it re-reads the
world through an independent channel and judges the effect —
VERIFIED (proven), FAILED (positively contradicted), UNKNOWN
(no usable evidence). These tests pin the verdict semantics,
the default spec table (decision-02 spec §3), both channels
(read tool + internal memory), and the fail-closed edges:
a verifier must never crash the executor, never re-dispatch a
non-read tool, and never call a missing spec a success.
"""
import unittest
from datetime import datetime, timedelta, timezone

from domain.planning.entities import PlanStep
from domain.planning.states import StepState
from features.planning.application.mapping import (
    plan_to_record,
    record_to_plan,
)
from domain.planning.entities import Plan
from features.planning.application.ports.verifier import Verdict
from features.planning.infrastructure.adapters.readback_verifier import (
    ReadBackVerifier,
)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat(timespec="seconds")
FUTURE = (NOW + timedelta(hours=24)).isoformat(timespec="seconds")

LEVELS = {
    "calendar_add": "execute",
    "calendar_delete": "destructive",
    "calendar_list": "read",
    "calendar_get": "read",
    "remember_fact": "write",
    "write_file": "write",
    "read_file": "read",
    "notify": "read",
}


def make_step(tool, args=None, verify=None):
    return PlanStep(
        step_id="s1",
        intent="خطوة تجريبية",
        tool=tool,
        args=args or {},
        state=StepState.RUNNING,
        idempotency_key="p_test:s1",
        verify=verify,
    )


class FakeDispatch:
    def __init__(self, payloads=None, raises=False):
        self.payloads = payloads or {}
        self.raises = raises
        self.calls = []

    def execute(self, tool, args):
        self.calls.append((tool, args))
        if self.raises:
            raise RuntimeError("dispatch down")
        return self.payloads.get(tool, {"ok": False})


def verifier(dispatch, memory_search=None):
    return ReadBackVerifier(
        dispatch=dispatch,
        memory_search=memory_search,
        tool_levels=LEVELS,
    )


ADD_ARGS = {
    "title": "مكالمة مع سعاد",
    # January dates ON PURPOSE: Africa/Casablanca is UTC+1 in
    # January under both the old and the post-2026 tzdata, so the
    # naive<->Zulu instant pairing below is stable on the phone
    # (stale tzdata), the VM and the VPS. Late-October dates are
    # exactly where the two tzdata versions disagree (+1 vs +0).
    "start": "2026-01-15T10:00:00",
    "end": "2026-01-15T11:00:00",
}
ADD_RESULT = {"ok": True, "event_id": "evt-1", "message": "تم"}


def get_payload(title="مكالمة مع سعاد", start="2026-01-15T09:00:00Z"):
    return {
        "ok": True,
        "found": True,
        "event": {
            "event_id": "evt-1",
            "title": title,
            "start": start,
            "end": "2026-01-15T10:00:00Z",
            "description": "",
        },
    }


class TestExemptSteps(unittest.TestCase):
    def test_read_tool_is_exempt(self):
        dispatch = FakeDispatch()
        outcome = verifier(dispatch).verify(
            make_step("read_file", {"path": "x"}), {"ok": True}
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)
        self.assertEqual(outcome.channel, "exempt")
        self.assertEqual(dispatch.calls, [])

    def test_notify_is_exempt(self):
        outcome = verifier(FakeDispatch()).verify(
            make_step("notify", {"text": "hi"}), {"ok": True}
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)


class TestCalendarAddVerification(unittest.TestCase):
    def test_matching_event_by_id_is_verified(self):
        dispatch = FakeDispatch({"calendar_get": get_payload()})
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS), ADD_RESULT
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)
        self.assertEqual(
            dispatch.calls, [("calendar_get", {"event_id": "evt-1"})]
        )

    def test_naive_start_matches_zulu_readback(self):
        # Step args carry the planner's naive local time; Google
        # stores the qualified instant. The comparison must be by
        # instant, not by string.
        dispatch = FakeDispatch({"calendar_get": get_payload()})
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS), ADD_RESULT
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)

    def test_missing_event_is_failed_not_unknown(self):
        dispatch = FakeDispatch(
            {"calendar_get": {"ok": True, "found": False}}
        )
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS), ADD_RESULT
        )
        self.assertIs(outcome.verdict, Verdict.FAILED)

    def test_wrong_title_is_failed(self):
        dispatch = FakeDispatch(
            {"calendar_get": get_payload(title="حدث آخر")}
        )
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS), ADD_RESULT
        )
        self.assertIs(outcome.verdict, Verdict.FAILED)
        self.assertIn("event.title", outcome.observed)

    def test_add_without_event_id_falls_back_to_day_list(self):
        dispatch = FakeDispatch(
            {
                "calendar_list": {
                    "ok": True,
                    "events": [
                        {
                            "event_id": "evt-9",
                            "title": "مكالمة مع سعاد",
                            "start": "2026-01-15T09:00:00Z",
                        }
                    ],
                }
            }
        )
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS),
            {"ok": True, "message": "تم"},
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)
        tool, args = dispatch.calls[0]
        self.assertEqual(tool, "calendar_list")
        self.assertEqual(args["time_min"], "2026-01-15T00:00:00")
        self.assertEqual(args["time_max"], "2026-01-15")

    def test_add_without_event_id_and_empty_day_is_failed(self):
        dispatch = FakeDispatch(
            {"calendar_list": {"ok": True, "events": []}}
        )
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS), {"ok": True}
        )
        self.assertIs(outcome.verdict, Verdict.FAILED)


class TestCalendarDeleteVerification(unittest.TestCase):
    def test_absent_event_is_verified(self):
        dispatch = FakeDispatch(
            {"calendar_get": {"ok": True, "found": False}}
        )
        outcome = verifier(dispatch).verify(
            make_step("calendar_delete", {"event_id": "evt-1"}),
            {"ok": True},
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)

    def test_surviving_event_is_failed(self):
        dispatch = FakeDispatch({"calendar_get": get_payload()})
        outcome = verifier(dispatch).verify(
            make_step("calendar_delete", {"event_id": "evt-1"}),
            {"ok": True},
        )
        self.assertIs(outcome.verdict, Verdict.FAILED)


class TestReadBackFailureIsUnknown(unittest.TestCase):
    def test_read_error_is_unknown(self):
        dispatch = FakeDispatch(
            {"calendar_get": {"ok": False, "error": "HTTP 500"}}
        )
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS), ADD_RESULT
        )
        self.assertIs(outcome.verdict, Verdict.UNKNOWN)

    def test_dispatch_exception_is_unknown_not_a_crash(self):
        dispatch = FakeDispatch(raises=True)
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS), ADD_RESULT
        )
        self.assertIs(outcome.verdict, Verdict.UNKNOWN)

    def test_no_spec_for_side_effect_tool_is_unknown(self):
        outcome = verifier(FakeDispatch()).verify(
            make_step("write_file", {"path": "x"}), {"ok": True}
        )
        self.assertIs(outcome.verdict, Verdict.UNKNOWN)


class TestMemoryChannel(unittest.TestCase):
    def test_saved_fact_found_is_verified(self):
        search = lambda query: [{"text": "رقم سعاد محفوظ"}]
        outcome = verifier(
            FakeDispatch(), memory_search=search
        ).verify(
            make_step("remember_fact", {"fact": "رقم سعاد محفوظ"}),
            {"ok": True},
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)
        self.assertEqual(outcome.channel, "memory")

    def test_missing_fact_is_failed(self):
        search = lambda query: []
        outcome = verifier(
            FakeDispatch(), memory_search=search
        ).verify(
            make_step("remember_fact", {"fact": "حقيقة"}),
            {"ok": True},
        )
        self.assertIs(outcome.verdict, Verdict.FAILED)

    def test_unwired_memory_channel_is_unknown(self):
        outcome = verifier(FakeDispatch()).verify(
            make_step("remember_fact", {"fact": "حقيقة"}),
            {"ok": True},
        )
        self.assertIs(outcome.verdict, Verdict.UNKNOWN)


class TestPlannerAuthoredSpec(unittest.TestCase):
    def test_explicit_spec_is_used(self):
        spec = {
            "read_tool": "calendar_get",
            "args": {"event_id": "{{step.args.event_id}}"},
            "predicate": "field_equals",
            "params": {"fields": {"found": True}},
        }
        dispatch = FakeDispatch({"calendar_get": get_payload()})
        outcome = verifier(dispatch).verify(
            make_step(
                "calendar_delete", {"event_id": "evt-1"}, verify=spec
            ),
            {"ok": True},
        )
        self.assertIs(outcome.verdict, Verdict.VERIFIED)

    def test_non_read_read_tool_is_refused_at_runtime(self):
        # A spec that bypassed plan-accept validation must still
        # never dispatch a write tool as a "read-back".
        spec = {
            "read_tool": "write_file",
            "args": {},
            "predicate": "field_equals",
            "params": {"fields": {"found": True}},
        }
        dispatch = FakeDispatch({"write_file": {"ok": True}})
        outcome = verifier(dispatch).verify(
            make_step("calendar_add", ADD_ARGS, verify=spec),
            ADD_RESULT,
        )
        self.assertIs(outcome.verdict, Verdict.UNKNOWN)
        self.assertEqual(dispatch.calls, [])

    def test_unresolvable_template_is_unknown(self):
        spec = {
            "read_tool": "calendar_get",
            "args": {"event_id": "{{step.result.missing}}"},
            "predicate": "field_equals",
            "params": {"fields": {"found": True}},
        }
        outcome = verifier(FakeDispatch()).verify(
            make_step("calendar_add", ADD_ARGS, verify=spec),
            ADD_RESULT,
        )
        self.assertIs(outcome.verdict, Verdict.UNKNOWN)


class TestVerifyOutcomeRoundTrip(unittest.TestCase):
    def test_verify_and_outcome_survive_the_store(self):
        step = make_step(
            "calendar_add",
            ADD_ARGS,
            verify={"channel": "memory"},
        )
        step.verify_outcome = {
            "verdict": "verified",
            "channel": "calendar_get",
            "predicate": "field_equals",
            "observed": "طابق",
        }
        plan = Plan(
            plan_id="p_test",
            goal="هدف",
            origin="interactive",
            steps=[step],
            created_at=NOW_ISO,
            updated_at=NOW_ISO,
            expires_at=FUTURE,
        )
        loaded = record_to_plan(plan_to_record(plan, NOW), NOW)
        self.assertEqual(loaded.steps[0].verify, {"channel": "memory"})
        self.assertEqual(
            loaded.steps[0].verify_outcome["verdict"], "verified"
        )


if __name__ == "__main__":
    unittest.main()
