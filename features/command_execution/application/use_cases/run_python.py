"""RunPython use case: authorize the script path, then run it."""
from features.command_execution.application.dto.run_python import RunPythonDTO
from features.command_execution.application.ports.script_authorization import (
    ScriptAuthorizationPort,
)
from features.command_execution.application.ports.script_runner import (
    ScriptRunnerPort,
)


class RunPythonUseCase:
    """Application logic for the run_python tool.

    The authorization gate only checks path confinement (via the port);
    existence, suffix and sandboxing decisions stay in the runner, which
    delegates to the hardened SafeExecutor.run_python.
    """

    def __init__(
        self,
        authorization: ScriptAuthorizationPort,
        runner: ScriptRunnerPort,
    ):
        self._authorization = authorization
        self._runner = runner

    def execute(self, dto: RunPythonDTO) -> dict:
        if not dto.script_path:
            return {
                "ok": False,
                "error": "script_path مطلوب.",
            }

        allowed, reason = self._authorization.can_run_script(
            dto.script_path
        )
        if not allowed:
            return {
                "ok": False,
                "error": reason or "غير مصرَّح بتشغيل هذا السكريبت.",
            }

        return self._runner.run_script(dto.script_path)
