"""Policy _PathsMixin (private)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from domain.rules import sensitive_paths
class _PathsMixin:
    """Methods moved verbatim."""

    def resolve_path(self, path: str) -> Optional[Path]:

        if not isinstance(path, str):
            return None

        if len(path) > self.max_path_length:
            return None

        path = path.strip()

        if not path:
            path = "."

        if "\x00" in path:
            return None

        try:
            candidate = Path(path)

            if not candidate.is_absolute():
                candidate = self.workspace / candidate

            candidate = candidate.resolve(strict=False)

        except (
            OSError,
            RuntimeError,
            ValueError,
        ):
            return None

        if not self.path_allowed(candidate):
            return None

        return candidate


    def path_allowed(self, path: Path) -> bool:

        try:
            path = Path(path).resolve(strict=False)
            workspace = self.workspace.resolve(strict=False)

            if path == workspace:
                return True

            return workspace in path.parents

        except (
            OSError,
            RuntimeError,
            ValueError,
        ):
            return False


    def is_sensitive_path(self, path: Path) -> bool:
        # Delegated to the pure domain rule
        # (domain/rules/sensitive_paths.py). Inputs are read live at call
        # time, so rebinding workspace (or the sensitive sets) after
        # __init__ keeps working -- exactly the pre-extraction semantics.
        # Guarded by test_policy_workspace_rebinding_after_init.
        return sensitive_paths.is_sensitive_path(
            path,
            self.workspace,
            self.sensitive_names,
            self.sensitive_directories,
            self.sensitive_extensions,
        )


    def validate_file_path(
        self,
        path: str,
        allow_sensitive: bool = False,
    ) -> Optional[Path]:

        target = self.resolve_path(path)

        if target is None:
            return None

        if not allow_sensitive and self.is_sensitive_path(target):
            return None

        return target


