from __future__ import annotations

from typing import Any

from features.memory.application.dto.remember_fact import RememberFactRequest


class RememberFactUseCase:
    """Persist a fact; authorization is checked before the runner."""

    def __init__(self, authorization: Any, runner: Any) -> None:
        self._authorization = authorization
        self._runner = runner

    def execute(self, request: RememberFactRequest) -> dict:
        if not self._authorization.can_remember(request.fact):
            return {
                "ok": False,
                "action": "remember_fact",
                "message": "الذاكرة فارغة.",
                "evidence": {},
            }
        return self._runner.run_remember(request.fact, request.is_preference)
