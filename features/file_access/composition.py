from __future__ import annotations

from typing import Any

from features.file_access.application.use_cases.read_file import ReadFileUseCase
from features.file_access.application.use_cases.write_file import WriteFileUseCase
from features.file_access.infrastructure.adapters.policy_authorization import (
    PolicyAuthorizationAdapter,
)
from features.file_access.infrastructure.adapters.workspace_file_storage import (
    WorkspaceFileStorageAdapter,
)
from features.file_access.interfaces.controllers.read_file_controller import (
    ReadFileController,
)
from features.file_access.interfaces.controllers.write_file_controller import (
    WriteFileController,
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


def build_write_file_controller(
    policy: Any,
) -> WriteFileController:
    storage = WorkspaceFileStorageAdapter(policy)
    authorization = PolicyAuthorizationAdapter(policy)
    use_case = WriteFileUseCase(
        storage=storage,
        authorization=authorization,
    )
    return WriteFileController(use_case)
