from __future__ import annotations

from typing import Any

from features.command_execution.application.dto.run_command import (
    RunCommandRequest,
)
from features.command_execution.application.use_cases.run_command import (
    RunCommandUseCase,
)


class RunCommandController:
    def __init__(self, use_case: RunCommandUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}

        request = RunCommandRequest(
            command=arguments.get("command", ""),
        )

        return self._use_case.execute(request)
