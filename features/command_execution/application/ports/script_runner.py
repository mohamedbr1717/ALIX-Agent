"""Port: script execution for run_python."""
from typing import Protocol


class ScriptRunnerPort(Protocol):
    """Runs a Python script and returns the standard result dict."""

    def run_script(self, script_path: str) -> dict:
        ...
