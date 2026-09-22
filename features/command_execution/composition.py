from __future__ import annotations
from features.command_execution.application.use_cases.run_python import RunPythonUseCase
from features.command_execution.infrastructure.adapters.executor_script_runner import ExecutorScriptRunnerAdapter
from features.command_execution.infrastructure.adapters.policy_script_authorization import PolicyScriptAuthorizationAdapter
from features.command_execution.interfaces.controllers.run_python_controller import RunPythonController

from typing import Any

from features.command_execution.application.use_cases.run_command import (
    RunCommandUseCase,
)
from features.command_execution.infrastructure.adapters.executor_command_runner import (
    ExecutorCommandRunnerAdapter,
)
from features.command_execution.infrastructure.adapters.policy_command_authorization import (
    PolicyCommandAuthorizationAdapter,
)
from features.command_execution.interfaces.controllers.run_command_controller import (
    RunCommandController,
)


def build_run_command_controller(
    policy: Any,
) -> RunCommandController:
    runner = ExecutorCommandRunnerAdapter(policy)
    authorization = PolicyCommandAuthorizationAdapter(policy)
    use_case = RunCommandUseCase(
        runner=runner,
        authorization=authorization,
    )
    return RunCommandController(use_case)


def build_run_python_controller(policy):
    """Build the run_python controller with its default adapters."""
    return RunPythonController(
        RunPythonUseCase(
            authorization=PolicyScriptAuthorizationAdapter(policy),
            runner=ExecutorScriptRunnerAdapter(policy),
        )
    )
