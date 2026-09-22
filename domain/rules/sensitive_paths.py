"""Pure domain rule: sensitive-path decisions for ALIX.

Framework-free: no Policy, no I/O, no side effects. The enterprise rule
"which paths must never be touched" as a pure function.

Design note: this is deliberately a *function*, not a bound object. An
earlier version froze workspace+sets into a dataclass at Policy.__init__
time -- but Policy.workspace is legitimately rebound after construction
(the file_access adapter tests do exactly this), so the rule read stale
state and wrongly denied in-workspace paths. All inputs are therefore
parameters, read live by the caller at call time.

Fail-closed: anything that cannot be resolved is treated as sensitive.
"""

from __future__ import annotations

from pathlib import Path
from typing import AbstractSet, Union

PathLike = Union[str, Path]


def is_sensitive_path(
    path: PathLike,
    workspace: Path,
    sensitive_names: AbstractSet[str] = frozenset(),
    sensitive_directories: AbstractSet[str] = frozenset(),
    sensitive_extensions: AbstractSet[str] = frozenset(),
) -> bool:
    """True if the path must be treated as sensitive / forbidden."""
    try:
        candidate = Path(path).resolve(strict=False)
        workspace = Path(workspace).resolve(strict=False)

        # Outside workspace = forbidden.
        if candidate != workspace and workspace not in candidate.parents:
            return True

        # Check every path component.
        for part in candidate.parts:
            if part in sensitive_names:
                return True

            if part in sensitive_directories:
                return True

        # Extension protection.
        if candidate.suffix.lower() in sensitive_extensions:
            return True

        return False

    except (
        OSError,
        RuntimeError,
        ValueError,
    ):
        return True
