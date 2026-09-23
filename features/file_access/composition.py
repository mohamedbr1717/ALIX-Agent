from __future__ import annotations
from features.file_access.application.use_cases.create_directory import CreateDirectoryUseCase
from features.file_access.infrastructure.adapters.executor_directory_runner import ExecutorDirectoryRunnerAdapter
from features.file_access.infrastructure.adapters.policy_directory_authorization import PolicyDirectoryAuthorizationAdapter
from features.file_access.interfaces.controllers.create_directory_controller import CreateDirectoryController

from typing import Any

from features.file_access.application.use_cases.delete_file import DeleteFileUseCase
from features.file_access.application.use_cases.read_file import ReadFileUseCase
from features.file_access.application.use_cases.write_file import WriteFileUseCase
from features.file_access.infrastructure.adapters.policy_authorization import (
    PolicyAuthorizationAdapter,
)
from features.file_access.infrastructure.adapters.workspace_file_storage import (
    WorkspaceFileStorageAdapter,
)
from features.file_access.interfaces.controllers.delete_file_controller import (
    DeleteFileController,
)
from features.file_access.interfaces.controllers.read_file_controller import (
    ReadFileController,
)
from features.file_access.interfaces.controllers.write_file_controller import (
    WriteFileController,
)


def build_delete_file_controller(
    policy: Any,
) -> DeleteFileController:
    storage = WorkspaceFileStorageAdapter(policy)
    authorization = PolicyAuthorizationAdapter(policy)
    use_case = DeleteFileUseCase(
        storage=storage,
        authorization=authorization,
    )
    return DeleteFileController(use_case)


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


def build_create_directory_controller(policy):
    """Build the create_directory controller with its default adapters."""
    authorization = PolicyDirectoryAuthorizationAdapter(policy)
    runner = ExecutorDirectoryRunnerAdapter(policy)
    use_case = CreateDirectoryUseCase(
        authorization=authorization,
        runner=runner,
    )
    return CreateDirectoryController(use_case)
