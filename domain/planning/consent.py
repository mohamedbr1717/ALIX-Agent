"""Destructive-step consent (Decision 7 — pure domain).

Owner's ruling (2026-11-04, «نفّذ الانقسام»): there is no single
rule for destructive steps — the authority of an approval splits
by supervision context and by whether the concrete action was
already fixed when the approval was given.

- Interactive plan, step fully concrete in the accepted draft and
  unchanged at execution: the step executes UNDER the plan
  approval — no second card. Enforcement is a digest: at
  acceptance the plan stamps ``consent_digest`` over the canonical
  (tool, args); the executor re-computes before dispatch and the
  pipeline re-verifies at its own confirmation gate. Any drift,
  a missing digest, or a step born after acceptance (decomposition)
  falls back to the pipeline's own per-call card.
- Scheduled plans: unchanged and stricter — a destructive step is
  born BLOCKED (SCHEDULED_POLICY) and never inherits anything.
- Tool-specific stricter rules override upward, never down: the
  tools in NEVER_INHERIT_CONSENT_TOOLS keep their own per-call
  confirmation even inside an approved interactive plan.

This module is pure stdlib (hashlib/json/hmac-free comparisons are
the caller's job) so the domain, the application layer and the
agent pipeline can all share ONE canonical digest — a second
implementation would be a second source of truth.
"""
from __future__ import annotations

import hashlib
import json

#: consent_source values recorded on a step (audit: every
#: destructive execution answers "under which approval?").
CONSENT_PLAN_CARD = "plan_card"
CONSENT_EXEC_CARD = "exec_card"

#: Tools that NEVER inherit plan consent (declared rule, in the
#: Decision-4 style). phone_call / send_sms carry the phone
#: bridge's standing ruling (2026-10-02): an explicit confirmation
#: for EVERY interactive operation, and Policy denies them in
#: scheduled mode outright. A plan card that happens to name the
#: number does not retire that per-call gate.
NEVER_INHERIT_CONSENT_TOOLS = frozenset({"phone_call", "send_sms"})


def consent_digest_for(tool: str, args: dict) -> str:
    """Canonical digest of one concrete action: (tool, args).

    Same serialization discipline as the application layer's
    hash_args (sorted keys, UTF-8, non-ASCII kept) so a digest
    stamped at acceptance and a digest computed at the gate are
    comparable byte-for-byte.
    """
    payload_obj = {"tool": str(tool), "args": args or {}}
    try:
        payload = json.dumps(
            payload_obj,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError):
        payload = repr(payload_obj)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def inherits_plan_consent(tool: str) -> bool:
    """True unless the tool carries a stricter per-call rule."""
    return tool not in NEVER_INHERIT_CONSENT_TOOLS
