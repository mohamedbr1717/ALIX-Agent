"""Capability data (Decision 5): what this agent can
actually do HERE, declared as data and resolved by probes.

Decision 5 (owner's rulings, 2026-11-01) — the live
capability ledger. A capability is a subject (a tool, or a
subsystem like an LLM leg) in a context, with a state:

    available / degraded / unavailable / unknown

"unknown" is a first-class honest state: it is never
promoted without evidence. Evidence comes in exactly two
state-changing kinds (the owner's ruling: observed outcomes
from the Decision-4 means log are display-only signals and
never change a state):

- DECLARED: facts the owner states as data (WhatsApp's WABA
  restriction; meta_publish deployed-but-unverified).
- PROBED: cheap, deterministic, side-effect-free checks
  (a binary on PATH, credential env vars present, the LLM
  router's own status report). No test calls, ever.

This module holds the declarations only; the probers live
in the application layer where the OS is reachable.
"""
from __future__ import annotations

AVAILABLE = "available"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"

SOURCE_PROBED = "probed"
SOURCE_DECLARED = "declared"

#: Tool -> requirement, resolved by side-effect-free probes.
#: Kinds:
#:   ("termux_binary", "<binary>") — available iff the
#:       Termux:API binary is on PATH (the phone gateway's
#:       own fail-closed check, moved to before the attempt).
#:   ("env_groups", ((VAR, ...), ...)) — available iff at
#:       least one credential group is fully present in the
#:       environment (names only; values are never read into
#:       the ledger, only their presence).
TOOL_REQUIREMENTS = {
    "notify": ("termux_binary", "termux-notification"),
    "phone_call": ("termux_binary", "termux-telephony-call"),
    "send_sms": ("termux_binary", "termux-sms-send"),
    "gmail_search": (
        "env_groups",
        (
            ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"),
            ("GMAIL_ADDRESS_2", "GMAIL_APP_PASSWORD_2"),
        ),
    ),
    "gmail_read": (
        "env_groups",
        (
            ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"),
            ("GMAIL_ADDRESS_2", "GMAIL_APP_PASSWORD_2"),
        ),
    ),
    "gmail_reply": (
        "env_groups",
        (
            ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"),
            ("GMAIL_ADDRESS_2", "GMAIL_APP_PASSWORD_2"),
        ),
    ),
    "gmail_send": (
        "env_groups",
        (
            ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"),
            ("GMAIL_ADDRESS_2", "GMAIL_APP_PASSWORD_2"),
        ),
    ),
    "calendar_add": (
        "env_groups",
        ((
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REFRESH_TOKEN",
        ),),
    ),
    "calendar_list": (
        "env_groups",
        ((
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REFRESH_TOKEN",
        ),),
    ),
    "calendar_get": (
        "env_groups",
        ((
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REFRESH_TOKEN",
        ),),
    ),
    "calendar_delete": (
        "env_groups",
        ((
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REFRESH_TOKEN",
        ),),
    ),
}

#: Tool -> (state, evidence): owner-declared facts that no
#: probe can see. These are data; changing one is an owner's
#: edit, reviewed like any other ruling.
DECLARED_STATES = {
    # Code-proven since 2026-10-12, but delivery is gated on
    # Meta business verification the owner has not completed:
    # configured, yet undeliverable — honestly unavailable.
    "whatsapp_send": (
        UNAVAILABLE,
        "WABA مقيّد: التحقق من النشاط التجاري مطلوب قبل أي "
        "تسليم (مُعلن من المالك، 2026-10-13)",
    ),
    # Phase 1 deployed 2026-10-2x but never live-proven; the
    # honest state is unknown, not available.
    "facebook_post_text": (
        UNKNOWN,
        "meta_publish منشور لكنه غير مُثبّت حيًّا بعد (مُعلن)",
    ),
    "facebook_post_photo": (
        UNKNOWN,
        "meta_publish منشور لكنه غير مُثبّت حيًّا بعد (مُعلن)",
    ),
}

#: LLM-leg subjects (kind "subsystem"), resolved from the
#: router's own status report when one is wired.
LLM_REMOTE = "llm_remote"
LLM_LOCAL = "llm_local"
