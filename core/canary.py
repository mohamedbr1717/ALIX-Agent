"""Honeytoken canary: tripwire for prompt-injection exfiltration.

A fake secret is published in the system prompt (see SYSTEM_GUARD_ADDENDUM).
It is never a real credential and no legitimate tool call ever needs it. If
the value appears inside tool-call arguments, the model is acting on injected
content (or leaking the prompt) -- the registry must deny the call loudly
(fail-closed).

The value is generated fresh per process, so an attacker cannot pre-know it.
"""
from __future__ import annotations

import secrets

_CANARY = "alix-ct-" + secrets.token_hex(16)


def get_canary() -> str:
    """The process-local honeytoken value."""
    return _CANARY


def find_canary(obj: object) -> str | None:
    """Return the canary value if it occurs anywhere inside obj.

    Recurses through dicts, lists and tuples; inspects every string.
    Returns None when the canary is absent.
    """
    if isinstance(obj, str):
        return _CANARY if _CANARY in obj else None
    if isinstance(obj, dict):
        for value in obj.values():
            hit = find_canary(value)
            if hit is not None:
                return hit
        return None
    if isinstance(obj, (list, tuple)):
        for value in obj:
            hit = find_canary(value)
            if hit is not None:
                return hit
        return None
    return None
