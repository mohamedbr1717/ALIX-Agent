"""Composition root for the history feature slice."""

from __future__ import annotations

from typing import Any

from features.history.application.use_cases.history_use_cases import (
    ListHistoryUseCase,
    LogActionUseCase,
    UndoLastUseCase,
)
from features.history.infrastructure.adapters.jsonl_action_store import (
    JsonlActionStore,
)
from features.history.interfaces.controllers.history_controller import (
    HistoryController,
    UndoController,
)


def build_history_controllers(
    policy: Any,
) -> dict[str, Any]:
    """Build history controllers sharing one store."""
    store = JsonlActionStore()
    return {
        "history": HistoryController(
            ListHistoryUseCase(store=store)
        ),
        "undo": UndoController(
            UndoLastUseCase(store=store), mark_store=store
        ),
        "log_action": LogActionUseCase(store=store),
    }
