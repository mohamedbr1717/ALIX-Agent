from __future__ import annotations

from typing import Any

from features.contacts.application.dto.resolve_contact import (
    ResolveContactRequest,
)


class ResolveContactController:
    """Builds a ResolveContactRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = ResolveContactRequest(
            name=str(arguments.get("name", "") or "").strip(),
        )
        return self._use_case.execute(request)
