"""Adapter: script execution delegated to SafeExecutor.run_python.

The adapter owns no execution logic of its own: SafeExecutor.run_python
is the hardened reference implementation (path validation, .py-only
suffix gate, ProotSandbox isolation, fail-closed when the real sandbox
is unavailable). SafeExecutor.__init__ does no I/O and is cheap, and the
agent constructs its executor with the same defaults, so a fresh
instance here is behaviorally identical.
"""
from core.executor import SafeExecutor
from core.policy import Policy


class ExecutorScriptRunnerAdapter:
    def __init__(self, policy: Policy):
        self._policy = policy

    def run_script(self, script_path: str) -> dict:
        return SafeExecutor(self._policy).run_python(script_path)
