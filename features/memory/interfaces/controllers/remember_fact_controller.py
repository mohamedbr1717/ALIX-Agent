from __future__ import annotations

from typing import Any

from features.memory.application.dto.remember_fact import RememberFactRequest


class RememberFactController:
    """Builds a RememberFactRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = RememberFactRequest(
            fact=str(arguments.get("fact", "")).strip(),
            is_preference=bool(arguments.get("is_preference", False)),
        )
        return self._use_case.execute(request)
