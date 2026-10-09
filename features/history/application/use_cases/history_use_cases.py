"""History use cases."""

from __future__ import annotations

from typing import Any

from features.history.application.dto.history import (
    HistoryResult,
    ListHistoryRequest,
    LogActionRequest,
)


class LogActionUseCase:
    """Record a tool execution (fire-and-forget, never raises)."""

    def __init__(self, store: Any):
        self._store = store

    def execute(self, request) -> None:
        """Accept LogActionRequest or plain dict."""
        try:
            if isinstance(request, dict):
                data = request
            else:
                data = {
                    "tool_name": request.tool_name,
                    "arguments": request.arguments,
                    "ok": request.ok,
                    "summary": request.summary,
                    "inverse": request.inverse,
                }
            self._store.append(data)
        except Exception:
            pass


class ListHistoryUseCase:
    """Show recent actions (read-only)."""

    def __init__(self, store: Any):
        self._store = store

    def execute(self, request: ListHistoryRequest) -> HistoryResult:
        actions = self._store.list_recent(
            max(1, min(request.limit, 30))
        )
        if not actions:
            return HistoryResult(
                ok=True, message="لا توجد إجراءات مسجلة بعد."
            )
        return HistoryResult(
            ok=True,
            message=f"آخر {len(actions)} إجراءات:",
            actions=actions,
        )


class UndoLastUseCase:
    """Reverse the most recent reversible action.

    Returns the inverse operation for the agent to execute via the
    normal tool pipeline (so policy/confirmation still apply).
    """

    def __init__(self, store: Any):
        self._store = store

    def execute(self) -> HistoryResult:
        actions = self._store.list_recent(30)
        for index, action in enumerate(actions):
            if not action.get("ok"):
                continue
            if action.get("undone"):
                continue
            inverse = action.get("inverse")
            if not inverse:
                continue
            return HistoryResult(
                ok=True,
                message=(
                    f"وجدت إجراءً قابلًا للتراجع: "
                    f"{action.get('tool_name')}."
                ),
                undone_action={
                    "index": index,
                    "original": action,
                    "inverse": inverse,
                },
            )
        return HistoryResult(
            ok=False,
            message="لا يوجد إجراء قابل للتراجع.",
        )
