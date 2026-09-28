"""Controller (interface adapter) for the search_code tool."""
from __future__ import annotations

from features.repo_context.application.dto.search_code import SearchCodeRequest
from features.repo_context.application.use_cases.search_code import SearchCodeUseCase


class SearchCodeController:
    """Translate raw tool arguments into a use-case request."""

    def __init__(self, use_case: SearchCodeUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        return self._use_case.execute(
            SearchCodeRequest(
                query=arguments.get("query", ""),
                root=arguments.get("root", ""),
                max_results=arguments.get("max_results", 50),
                case_sensitive=arguments.get("case_sensitive", False),
            )
        )
