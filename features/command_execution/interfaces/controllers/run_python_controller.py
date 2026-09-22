"""Controller for the run_python tool: arguments -> DTO -> use case."""
from features.command_execution.application.dto.run_python import RunPythonDTO
from features.command_execution.application.use_cases.run_python import (
    RunPythonUseCase,
)


class RunPythonController:
    def __init__(self, use_case: RunPythonUseCase):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        return self._use_case.execute(
            RunPythonDTO.from_arguments(arguments)
        )
