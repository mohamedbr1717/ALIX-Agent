"""Controller (interface adapter) for the git_status tool."""
from __future__ import annotations

from features.system.application.dto.git_status import GitStatusRequest
from features.system.application.use_cases.git_status import GitStatusUseCase


class GitStatusController:
    """Translate raw tool arguments into a use-case request."""

    def __init__(self, use_case: GitStatusUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        # The old agent.py dispatch hardcoded "status"; the registry path
        # passed arguments through with executor default "status".
        request = GitStatusRequest(
            action=arguments.get("action", "status"),
        )
        return self._use_case.execute(request)
