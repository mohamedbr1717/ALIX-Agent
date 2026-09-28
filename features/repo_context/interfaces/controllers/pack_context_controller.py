"""Controller (interface adapter) for the pack_context tool."""
from __future__ import annotations

from features.repo_context.application.dto.pack_context import PackContextRequest
from features.repo_context.application.use_cases.pack_context import PackContextUseCase


class PackContextController:
    """Translate raw tool arguments into a use-case request."""

    def __init__(self, use_case: PackContextUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        return self._use_case.execute(
            PackContextRequest(
                root=arguments.get("root", ""),
                focus=arguments.get("focus", []),
                max_tokens=arguments.get("max_tokens", 4000),
                max_files=arguments.get("max_files", 20),
            )
        )
