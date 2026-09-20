from __future__ import annotations

from typing import Any

from features.file_access.application.use_cases.read_file import ReadFileUseCase
from features.file_access.infrastructure.adapters.policy_authorization import (
    PolicyAuthorizationAdapter,
)
from features.file_access.infrastructure.adapters.workspace_file_storage import (
    WorkspaceFileStorageAdapter,
)
from features.file_access.interfaces.controllers.read_file_controller import (
    ReadFileController,
)


def build_read_file_controller(
    policy: Any,
) -> ReadFileController:
    storage = WorkspaceFileStorageAdapter(policy)
    authorization = PolicyAuthorizationAdapter(policy)
    use_case = ReadFileUseCase(
        storage=storage,
        authorization=authorization,
    )
    return ReadFileController(use_case)
