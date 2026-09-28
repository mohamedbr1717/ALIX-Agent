"""Pure domain rules for repo-context root allowlisting (no I/O)."""
from __future__ import annotations

from pathlib import Path


def normalize_root(root: str) -> str:
    """Expand ~ and resolve lexically (no existence check)."""
    return str(Path(root).expanduser().resolve(strict=False))


def is_root_allowed(root: str, allowed_roots: list) -> bool:
    """True when the normalized root equals or sits inside an allowed root.

    Fail-closed: any unparseable root or empty allowlist denies.
    """
    try:
        candidate = Path(normalize_root(root))
    except (OSError, ValueError, RuntimeError):
        return False
    for allowed in allowed_roots:
        try:
            base = Path(normalize_root(allowed))
        except (OSError, ValueError, RuntimeError):
            continue
        if candidate == base or base in candidate.parents:
            return True
    return False
