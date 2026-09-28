"""Controller (interface adapter) for the repo_map tool."""
from __future__ import annotations

from features.repo_context.application.dto.repo_map import RepoMapRequest
from features.repo_context.application.use_cases.repo_map import RepoMapUseCase


class RepoMapController:
    """Translate raw tool arguments into a use-case request."""

    def __init__(self, use_case: RepoMapUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        return self._use_case.execute(
            RepoMapRequest(
                root=arguments.get("root", ""),
                max_depth=arguments.get("max_depth", 6),
                max_entries=arguments.get("max_entries", 400),
            )
        )
