"""Port: script-execution authorization for run_python."""
from typing import Optional, Protocol, Tuple


class ScriptAuthorizationPort(Protocol):
    """Decides whether a script path may be executed."""

    def can_run_script(
        self, script_path: str
    ) -> Tuple[bool, Optional[str]]:
        """Return (allowed, denial_reason). reason is None when allowed."""
        ...
