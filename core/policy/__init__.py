"""Policy facade (public API unchanged)."""
from __future__ import annotations

import shlex  # re-exported: tests patch "core.policy.shlex.split"

from ._config import _ConfigMixin
from ._paths import _PathsMixin
from ._commands import _CommandsMixin
from ._tools import _ToolsMixin
from ._scheduled import _ScheduledMixin
from ._arguments import _ArgumentsMixin

class Policy(
    _ConfigMixin,
    _PathsMixin,
    _CommandsMixin,
    _ToolsMixin,
    _ScheduledMixin,
    _ArgumentsMixin,
):
    """Security policy facade."""
    pass

__all__ = ["Policy", "shlex"]
