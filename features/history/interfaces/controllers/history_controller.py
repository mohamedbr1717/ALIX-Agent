"""History controllers."""

from __future__ import annotations

from typing import Any

from features.history.application.dto.history import ListHistoryRequest


class HistoryController:
    """history tool handler (read-only)."""

    def __init__(self, use_case: Any):
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = ListHistoryRequest(
            limit=int(arguments.get("limit", 10) or 10)
        )
        result = self._use_case.execute(request)
        payload = {"ok": result.ok, "message": result.message}
        if result.actions:
            # Present newest-first with reversible flags.
            payload["actions"] = [
                {
                    "tool": a.get("tool_name"),
                    "time": a.get("timestamp"),
                    "ok": a.get("ok"),
                    "summary": a.get("summary"),
                    "reversible": bool(
                        a.get("ok")
                        and not a.get("undone")
                        and a.get("inverse")
                    ),
                    "undone": bool(a.get("undone")),
                }
                for a in result.actions
            ]
        return payload


class UndoController:
    """undo tool handler.

    Finds the most recent reversible action and returns its inverse
    operation. The agent executes the inverse via the normal pipeline.
    """

    def __init__(self, use_case: Any, mark_store: Any):
        self._use_case = use_case
        self._mark_store = mark_store

    def handle(self, arguments: dict) -> dict:
        result = self._use_case.execute()
        if not result.ok or not result.undone_action:
            return {"ok": False, "message": result.message}
        return {
            "ok": True,
            "message": result.message,
            "undone_action": result.undone_action,
        }
