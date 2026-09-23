"""Controller (interface adapter) for the system_info tool."""
from __future__ import annotations

from features.system.application.dto.system_info import SystemInfoRequest
from features.system.application.use_cases.system_info import SystemInfoUseCase


class SystemInfoController:
    """Translate raw tool arguments into a use-case request."""

    def __init__(self, use_case: SystemInfoUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        return self._use_case.execute(SystemInfoRequest())
