from __future__ import annotations

from typing import Any

from core.memory import Memory
from features.memory.application.use_cases.remember_fact import (
    RememberFactUseCase,
)
from features.memory.infrastructure.adapters.fact_authorization import (
    FactAuthorizationAdapter,
)
from features.memory.infrastructure.adapters.memory_fact_runner import (
    MemoryFactRunnerAdapter,
)
from features.memory.interfaces.controllers.remember_fact_controller import (
    RememberFactController,
)


def build_remember_fact_controller(
    memory: Any | None = None,
) -> RememberFactController:
    """Build the remember_fact controller.

    The agent injects its shared Memory instance; other callers
    (e.g. ToolRegistry) get a default Memory on the same store.
    """
    if memory is None:
        memory = Memory()
    authorization = FactAuthorizationAdapter()
    runner = MemoryFactRunnerAdapter(memory)
    use_case = RememberFactUseCase(
        authorization=authorization,
        runner=runner,
    )
    return RememberFactController(use_case)
