"""Composition root for the system feature (read-only introspection)."""
from __future__ import annotations

from features.system.application.use_cases.git_status import GitStatusUseCase
from features.system.application.use_cases.system_info import SystemInfoUseCase
from features.system.infrastructure.adapters.executor_system_runner import (
    ExecutorSystemRunnerAdapter,
)
from features.system.infrastructure.adapters.policy_system_authorization import (
    PolicySystemAuthorizationAdapter,
)
from features.system.interfaces.controllers.git_status_controller import (
    GitStatusController,
)
from features.system.interfaces.controllers.system_info_controller import (
    SystemInfoController,
)


def build_system_info_controller(policy):
    """Build the system_info controller with its default adapters."""
    authorization = PolicySystemAuthorizationAdapter(policy)
    runner = ExecutorSystemRunnerAdapter(policy)
    use_case = SystemInfoUseCase(
        authorization=authorization,
        runner=runner,
    )
    return SystemInfoController(use_case)


def build_git_status_controller(policy):
    """Build the git_status controller with its default adapters."""
    authorization = PolicySystemAuthorizationAdapter(policy)
    runner = ExecutorSystemRunnerAdapter(policy)
    use_case = GitStatusUseCase(
        authorization=authorization,
        runner=runner,
    )
    return GitStatusController(use_case)
