from __future__ import annotations

from typing import Protocol


class PhoneAuthorization(Protocol):
    """Policy gate for phone actions (defense in depth).

    The agent core already enforces Policy.requires_confirmation and
    Policy.scheduled_tool_permitted before the handler runs; this port
    lets the use case fail closed if the wiring is ever wrong.
    """

    def can_call(self, number: str) -> bool: ...
    def can_text(self, number: str) -> bool: ...
    def can_notify(self) -> bool: ...
