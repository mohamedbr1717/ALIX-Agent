"""Composition root for the planning feature (Decision 1).

build_planning_controller wires the full slice (planner +
executor) for the agent seam; build_plan_admin_controller wires
only the store-backed operations (plan_status / plan_cancel tool
handlers, recovery, owner release) for callers that have no LLM
or dispatch path — notably core/feature_bridge's migrated-tool
registry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from features.planning.application.ports.plan_notifier import (
    PlanNotifierPort,
)
from features.planning.application.use_cases.cancel_plan import (
    CancelPlanUseCase,
)
from features.planning.application.use_cases.create_plan import (
    CreatePlanUseCase,
)
from features.planning.application.use_cases.decompose_step import (
    DecomposeStepUseCase,
)
from features.planning.application.use_cases.get_plan import (
    GetPlanUseCase,
)
from features.planning.application.use_cases.helpers import (
    system_clock,
)
from features.planning.application.use_cases.list_plans import (
    ListPlansUseCase,
)
from features.planning.application.use_cases.recover_plans import (
    RecoverPlansUseCase,
)
from features.planning.application.use_cases.release_step import (
    ReleaseStepUseCase,
)
from features.planning.application.use_cases.run_plan import (
    RunPlanUseCase,
)
from features.planning.infrastructure.adapters.contract_ok_verifier import (
    ContractOkVerifier,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    JsonPlanStore,
)
from features.planning.infrastructure.adapters.llm_planner import (
    LLMPlannerAdapter,
)
from features.planning.infrastructure.adapters.tool_dispatch import (
    CallableToolDispatch,
)
from features.planning.interfaces.controllers.planning_controller import (
    PlanningController,
)
from features.planning.interfaces.notifier import PlanNotifier


def build_plan_store(
    path: Optional[Path] = None,
) -> JsonPlanStore:
    """Build the plan store (shared by tools and the executor)."""
    return JsonPlanStore(path)


def _store_for(base_dir) -> JsonPlanStore:
    if base_dir is None:
        return JsonPlanStore()
    return JsonPlanStore(
        Path(base_dir) / "planning" / "plans.json"
    )


def _admin_parts(store, clock, notifier):
    return {
        "get_plan": GetPlanUseCase(store=store, clock=clock),
        "list_plans": ListPlansUseCase(
            store=store, clock=clock
        ),
        "cancel_plan": CancelPlanUseCase(
            store=store, clock=clock
        ),
        "release_step": ReleaseStepUseCase(
            store=store, clock=clock
        ),
        "recover_plans": RecoverPlansUseCase(
            store=store, clock=clock, notifier=notifier
        ),
    }


def build_plan_admin_controller(
    base_dir=None,
    clock: Optional[Callable] = None,
    notify_fn: Optional[Callable] = None,
) -> PlanningController:
    """Store-backed controller: status/cancel/release/recover."""
    clock = clock or system_clock
    store = _store_for(base_dir)
    notifier = PlanNotifier(sender=notify_fn, clock=clock)
    return PlanningController(
        **_admin_parts(store, clock, notifier),
        notifier=notifier,
        clock=clock,
    )


def build_planning_controller(
    *,
    llm=None,
    execute_tool: Optional[Callable] = None,
    base_dir=None,
    notify_fn: Optional[Callable] = None,
    clock: Optional[Callable] = None,
    allowlist: frozenset = frozenset(),
    tool_schemas: Optional[dict] = None,
    destructive_tools: frozenset = frozenset(),
    confirming_tools: frozenset = frozenset(),
) -> PlanningController:
    """Full controller: creation + deterministic execution.

    Without ``llm`` or ``execute_tool`` the create/run face is
    unavailable (try_create_and_run reports handled=False) while
    the admin face keeps working — the same object the bridge
    builds for the agent always passes both.
    """
    clock = clock or system_clock
    store = _store_for(base_dir)
    notifier: PlanNotifierPort = PlanNotifier(
        sender=notify_fn, clock=clock
    )
    tool_schemas = tool_schemas or {}

    create_plan = None
    run_plan = None
    if llm is not None:
        planner = LLMPlannerAdapter(llm)
        create_plan = CreatePlanUseCase(
            planner=planner,
            store=store,
            allowlist=frozenset(allowlist),
            tool_schemas=tool_schemas,
            destructive_tools=frozenset(destructive_tools),
            confirming_tools=frozenset(confirming_tools),
            clock=clock,
            notifier=notifier,
        )
        if execute_tool is not None:
            decompose = DecomposeStepUseCase(
                planner=planner,
                store=store,
                allowlist=frozenset(allowlist),
                tool_schemas=tool_schemas,
                destructive_tools=frozenset(destructive_tools),
                clock=clock,
                notifier=notifier,
            )
            run_plan = RunPlanUseCase(
                dispatch=CallableToolDispatch(execute_tool),
                verifier=ContractOkVerifier(),
                store=store,
                decompose=decompose,
                clock=clock,
                notifier=notifier,
            )

    return PlanningController(
        **_admin_parts(store, clock, notifier),
        create_plan=create_plan,
        run_plan=run_plan,
        notifier=notifier,  # type: ignore[arg-type]
        clock=clock,
    )
