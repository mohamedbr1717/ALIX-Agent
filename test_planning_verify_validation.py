"""Decision 2 — verify-spec validation at plan-accept time.

A verify spec names the read-back channel for a step. A plan
carrying a spec that could write (a non-read read_tool), names
no channel or two, or uses an unknown predicate must be rejected
WHOLE at acceptance — the same fail-closed posture as step keys
and args. With no read tools configured, any tool-channel spec
is rejected (safe default).
"""
import unittest

from domain.planning.validation import (
    PlanRejected,
    validate_step_list,
)

ALLOWLIST = frozenset({"calendar_add", "calendar_get", "remember_fact"})
SCHEMAS = {
    "calendar_add": frozenset({"title", "start", "end"}),
    "calendar_get": frozenset({"event_id"}),
    "remember_fact": frozenset({"fact"}),
}
READ_TOOLS = frozenset({"calendar_get", "calendar_list"})


def step(**overrides):
    base = {
        "intent": "أضف حدثًا",
        "tool": "calendar_add",
        "args": {"title": "t", "start": "s", "end": "e"},
    }
    base.update(overrides)
    return base


def validate(steps, read_tools=READ_TOOLS):
    return validate_step_list(
        steps,
        ALLOWLIST,
        SCHEMAS,
        max_steps=12,
        read_tools=read_tools,
    )


GOOD_SPEC = {
    "read_tool": "calendar_get",
    "args": {"event_id": "{{step.result.event_id}}"},
    "predicate": "field_equals",
    "params": {"fields": {"found": True}},
}


class TestVerifySpecValidation(unittest.TestCase):
    def test_valid_tool_spec_accepted_and_carried(self):
        result = validate([step(verify=dict(GOOD_SPEC))])
        self.assertNotIsInstance(result, PlanRejected)
        self.assertEqual(result[0].verify["read_tool"], "calendar_get")

    def test_valid_memory_channel_spec_accepted(self):
        spec = {
            "channel": "memory",
            "args": {"query": "{{step.args.fact}}"},
            "predicate": "exists_matching",
            "params": {"match": {"text": "{{step.args.fact}}"}},
        }
        result = validate([step(tool="remember_fact",
                                  args={"fact": "x"}, verify=spec)])
        self.assertNotIsInstance(result, PlanRejected)

    def test_no_verify_key_still_accepted(self):
        result = validate([step()])
        self.assertNotIsInstance(result, PlanRejected)
        self.assertIsNone(result[0].verify)

    def test_write_tool_as_read_tool_rejected(self):
        spec = dict(GOOD_SPEC, read_tool="calendar_add")
        result = validate([step(verify=spec)])
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "verify_spec_invalid")

    def test_unknown_predicate_rejected(self):
        spec = dict(GOOD_SPEC, predicate="looks_fine")
        result = validate([step(verify=spec)])
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "verify_spec_invalid")

    def test_two_channels_rejected(self):
        spec = dict(GOOD_SPEC, channel="memory")
        result = validate([step(verify=spec)])
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "verify_spec_invalid")

    def test_no_channel_rejected(self):
        spec = {"predicate": "field_equals", "params": {}}
        result = validate([step(verify=spec)])
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "verify_spec_invalid")

    def test_unknown_channel_rejected(self):
        spec = {
            "channel": "web",
            "predicate": "field_equals",
            "params": {},
        }
        result = validate([step(verify=spec)])
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "verify_spec_invalid")

    def test_spec_extra_key_rejected(self):
        spec = dict(GOOD_SPEC, execute="rm -rf")
        result = validate([step(verify=spec)])
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "verify_spec_invalid")

    def test_no_read_tools_configured_rejects_tool_specs(self):
        result = validate(
            [step(verify=dict(GOOD_SPEC))], read_tools=frozenset()
        )
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "verify_spec_invalid")

    def test_verify_does_not_open_the_smuggling_door(self):
        forged = step(verify=dict(GOOD_SPEC), state="succeeded")
        result = validate([forged])
        self.assertIsInstance(result, PlanRejected)
        self.assertEqual(result.reason, "step_keys_mismatch")


if __name__ == "__main__":
    unittest.main()
