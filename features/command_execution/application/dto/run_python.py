"""DTO for the run_python tool."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RunPythonDTO:
    """Validated arguments for running a Python script."""

    script_path: str

    @classmethod
    def from_arguments(cls, arguments: dict) -> "RunPythonDTO":
        args = arguments or {}
        return cls(script_path=str(args.get("script_path", "") or ""))
