"""Adapter: script authorization backed by Policy.validate_file_path."""
from core.policy import Policy


class PolicyScriptAuthorizationAdapter:
    """Authorization gate: the script must resolve inside the workspace
    and must not be a sensitive path."""

    def __init__(self, policy: Policy):
        self._policy = policy

    def can_run_script(self, script_path: str):
        if self._policy.validate_file_path(script_path) is None:
            return False, "مسار السكريبت غير مسموح أو حساس."
        return True, None
