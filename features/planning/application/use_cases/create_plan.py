"""create_plan use case: draft -> validate -> assemble -> save.

The planner is called exactly once. Its output is untrusted: the
domain validation either accepts the draft whole or rejects it
whole, and every identifier/timestamp/budget is assigned HERE by
code — never by the model (spec §4.2 / §4.6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, List, Optional

from domain.planning.entities import (
    PLAN_TTL_HOURS,
    Plan,
    PlanStep,
    PriorAction,
)
from domain.planning.consent import (
    CONSENT_PLAN_CARD,
    consent_digest_for,
    inherits_plan_consent,
)
from domain.planning.ask import (
    ASK_REPEAT_COOLDOWN_DAYS,
    MAX_QUESTION_CHARS,
    clarification_key,
    disclosure_lines,
    scheduled_ask_question,
    unverifiable_write_steps,
)
from domain.planning.means import (
    BANNED_TOOL_CONTEXTS,
    PREFERENCE_NOTES,
)
from domain.planning.states import BlockedReason, StepState
from domain.planning.validation import (
    PlanRejected,
    validate_plan_draft,
)

from features.planning.application.dto.planning import (
    CreatePlanRequest,
)
from features.planning.application.mapping import plan_to_record
from features.planning.application.ports.ask_ledger import (
    AskLedgerPort,
)
from features.planning.application.ports.plan_notifier import (
    PlanNotifierPort,
)
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.ports.planner import PlannerPort
from features.planning.application.use_cases.helpers import (
    hash_args,
    iso,
    new_plan_id,
    truncate_stored,
)


#: Tools whose only effect is retrieving information for an
#: answer. A plan built ONLY from these is not a plan at all —
#: it is a question wearing a plan's clothes (planner question-
#: gate fix, 2026-10-31: a pure Q&A endurance-escalated into
#: plan p_20261030T232235_fdf7 and died there with no answer).
#: Such drafts are declined at creation and the caller falls
#: back to the plain loop / research path, which answers from
#: search results directly. Any single step outside this set
#: (a write, a send, a memory fact, ...) makes the draft a
#: genuine plan again — the owner's mixed-request ruling.
RESEARCH_ONLY_TOOLS = frozenset({"web_search", "web_fetch"})


@dataclass
class CreatePlanOutcome:
    created: bool
    plan: Optional[Plan] = None
    reason: str = ""  # rejection reason when created is False
    detail: str = ""
    # Single-ask: True when this clarification was already
    # delivered for the same scheduled goal inside the
    # cooldown and the notification was suppressed.
    ask_repeated: bool = False


class CreatePlanUseCase:
    """Application service: build a validated, persisted plan."""

    def __init__(
        self,
        *,
        planner: PlannerPort,
        store: PlanStorePort,
        allowlist: frozenset,
        tool_schemas: dict,
        destructive_tools: frozenset,
        confirming_tools: frozenset,
        clock: Callable,
        notifier: Optional[PlanNotifierPort] = None,
        read_tools: frozenset = frozenset(),
        runtime_tags: frozenset = frozenset(),
        means_hints_provider=None,
        capabilities_provider=None,
        tool_levels: dict = None,
        verifiable_tools: frozenset = frozenset(),
        ask_ledger: Optional[AskLedgerPort] = None,
    ):
        self._planner = planner
        self._store = store
        self._allowlist = allowlist
        self._tool_schemas = tool_schemas
        self._destructive_tools = destructive_tools
        self._confirming_tools = confirming_tools
        self._clock = clock
        self._notifier = notifier
        self._read_tools = read_tools
        self._runtime_tags = runtime_tags
        self._means_hints_provider = means_hints_provider
        self._capabilities_provider = capabilities_provider
        self._tool_levels = dict(tool_levels or {})
        self._verifiable_tools = verifiable_tools
        self._ask_ledger = ask_ledger

    # -- Decision 6 notification helpers: a failed or absent
    # notification channel never fails creation (port rule).

    def _notify_clarification(self, goal: str, question: str) -> None:
        if self._notifier is None:
            return
        fn = getattr(self._notifier, "clarification", None)
        if callable(fn):
            try:
                fn(goal, question)
            except Exception:
                pass

    def _ask_gate(self, request) -> bool:
        """Single-ask gate (owner's principle, 2026-11-01).

        Returns True when this clarification may be DELIVERED.
        Interactive asks always deliver (the owner is present;
        the conversation is the channel). Scheduled asks are
        recorded in the ask ledger and delivered at most once
        per ASK_REPEAT_COOLDOWN_DAYS per goal: a recurring
        task whose question went unanswered stays silent on
        later runs instead of demanding an answer every time.
        No ledger wired → legacy behavior (always deliver)."""
        if request.origin != "scheduled" or self._ask_ledger is None:
            return True
        key = clarification_key(request.goal)
        now = self._clock()
        try:
            last = self._ask_ledger.last_asked(key)
        except Exception:
            last = None
        if last is not None:
            try:
                if now - last < timedelta(
                    days=ASK_REPEAT_COOLDOWN_DAYS
                ):
                    return False
            except TypeError:
                pass  # incomparable timestamps: deliver (ask once more)
        try:
            self._ask_ledger.record(key, now)
        except Exception:
            pass
        return True

    def _notify_notices(self, plan, notices) -> None:
        fn = getattr(self._notifier, "plan_notices", None)
        if callable(fn):
            try:
                fn(plan, notices)
            except Exception:
                pass

    def execute(
        self, request: CreatePlanRequest
    ) -> CreatePlanOutcome:
        prior_actions = [
            PriorAction(
                tool=str(tool),
                args_hash=hash_args(args or {}),
                result_ref=truncate_stored(result_text or ""),
            )
            for (tool, args, result_text) in request.prior_actions
        ]

        # Decision 5: the capability ledger's view of THIS
        # context — tools proven unavailable here leave the
        # planner's listing, and the ledger's notes ride as
        # data. A broken ledger never blocks planning (the
        # seam degrades to no exclusions, no notes).
        cap_excluded: frozenset = frozenset()
        cap_notes: list = []
        if self._capabilities_provider is not None:
            try:
                cap_excluded, cap_notes = (
                    self._capabilities_provider()
                )
            except Exception:
                cap_excluded, cap_notes = frozenset(), []

        context = {
            "origin": request.origin,
            "tools": sorted(self._allowlist - cap_excluded),
            "tool_args": {
                name: sorted(keys)
                for name, keys in self._tool_schemas.items()
                if name not in cap_excluded
            },
        }
        if cap_notes:
            context["capability_notes"] = cap_notes

        # Decision 4 (advisory): the means log's evidence and
        # the owner's declared preference notes ride into the
        # planner's context as DATA. Advice only — acceptance
        # below is unchanged, and a broken log never blocks
        # planning (the provider seam degrades to no hints).
        hints: list = []
        if self._means_hints_provider is not None:
            try:
                hints = list(self._means_hints_provider())
            except Exception:
                hints = []
        hints.extend(PREFERENCE_NOTES)
        if hints:
            context["means_hints"] = hints

        try:
            draft = self._planner.plan(
                request.goal, prior_actions, context
            )
        except Exception as exc:  # planner transport failure
            return CreatePlanOutcome(
                created=False,
                reason="planner_error",
                detail=type(exc).__name__,
            )

        # Decision 6 (clarify channel): the planner may answer
        # with a question instead of a draft when a required
        # detail cannot be derived — the structured alternative
        # to inventing values. No plan is created; the question
        # is the outcome, delivered via the notifier and the
        # controller's reply. A malformed clarify falls through
        # to validation and is rejected like any bad draft.
        if (
            isinstance(draft, dict)
            and "steps" not in draft
            and isinstance(draft.get("clarify"), str)
            and draft["clarify"].strip()
        ):
            question = draft["clarify"].strip()[
                :MAX_QUESTION_CHARS
            ]
            deliver = self._ask_gate(request)
            if deliver:
                self._notify_clarification(request.goal, question)
            return CreatePlanOutcome(
                created=False,
                reason="clarification_needed",
                detail=question,
                ask_repeated=not deliver,
            )

        validated = validate_plan_draft(
            draft,
            self._allowlist,
            self._tool_schemas,
            read_tools=self._read_tools,
        )
        if isinstance(validated, PlanRejected):
            return CreatePlanOutcome(
                created=False,
                reason=validated.reason,
                detail=validated.detail,
            )

        if len(validated) < max(1, request.min_steps):
            return CreatePlanOutcome(
                created=False,
                reason="below_min_steps",
                detail=f"{len(validated)} steps",
            )

        # Decision 4 (declared rules): a tool banned in this
        # runtime context (a mechanical capability fact, e.g.
        # notify on a server without Termux:API) rejects the
        # draft whole — the caller falls back safely, exactly
        # like every other acceptance rejection.
        for vstep in validated:
            banned_in = [
                tag
                for (tool, tag) in BANNED_TOOL_CONTEXTS
                if tool == vstep.tool and tag in self._runtime_tags
            ]
            if banned_in:
                return CreatePlanOutcome(
                    created=False,
                    reason="means_rule_banned",
                    detail=(
                        f"{vstep.tool} banned in context "
                        f"{banned_in[0]} (declared Decision-4 rule)"
                    ),
                )

        # Decision 5 (pre-flight at acceptance): a draft that
        # still binds a tool the ledger proves unavailable in
        # this context is rejected whole — listing exclusion
        # is a hint to a model, this is the guarantee.
        for vstep in validated:
            if vstep.tool in cap_excluded:
                return CreatePlanOutcome(
                    created=False,
                    reason="capability_unavailable",
                    detail=(
                        f"{vstep.tool} unavailable in this "
                        "context (Decision-5 capability ledger)"
                    ),
                )

        # Decision 6 (ask rule): in a scheduled context, a
        # write step whose effect cannot be verified asks
        # BEFORE anything runs — no plan is created and the
        # question goes out through the notifier. Interactive
        # requests execute without asking (owner's ruling);
        # their hits become disclosure lines on the created
        # plan's notice instead (computed at creation below).
        ask_hits = unverifiable_write_steps(
            validated,
            tool_levels=self._tool_levels,
            verifiable_tools=self._verifiable_tools,
        )
        if ask_hits and request.origin == "scheduled":
            question = scheduled_ask_question(ask_hits)
            deliver = self._ask_gate(request)
            if deliver:
                self._notify_clarification(request.goal, question)
            return CreatePlanOutcome(
                created=False,
                reason="clarification_needed",
                detail=question,
                ask_repeated=not deliver,
            )

        if all(
            vstep.tool in RESEARCH_ONLY_TOOLS for vstep in validated
        ):
            # Question-gate (2026-10-31): an all-research draft
            # is an information request, not a task — decline so
            # the agent answers it in the plain loop instead of
            # stranding it in the plan executor.
            return CreatePlanOutcome(
                created=False,
                reason="research_not_plannable",
                detail=(
                    "all steps are research reads: "
                    + ", ".join(v.tool for v in validated)
                ),
            )

        now = self._clock()
        now_iso = iso(now)
        plan_id = new_plan_id(now)

        steps: List[PlanStep] = []
        for index, vstep in enumerate(validated, start=1):
            step_id = f"s{index}"
            blocked_reason = None
            state = StepState.PENDING
            if (
                request.origin == "scheduled"
                and vstep.tool in self._destructive_tools
            ):
                # Spec §4.4: a destructive step in a scheduled
                # plan is born BLOCKED and never reaches the
                # executor — stricter than the interactive path,
                # deliberately.
                state = StepState.BLOCKED
                blocked_reason = BlockedReason.SCHEDULED_POLICY
            consent_digest = None
            consent_source = None
            if (
                request.origin == "interactive"
                and state is StepState.PENDING
                and vstep.tool in self._destructive_tools
                and inherits_plan_consent(vstep.tool)
            ):
                # Decision 7 (owner's split ruling, 2026-11-04):
                # an interactive destructive step whose concrete
                # (tool, args) this accepted draft fixes executes
                # under the plan approval — the digest is the
                # enforcement: any later drift revokes the
                # inheritance and the step falls back to its own
                # card at execution. Tools with a stricter
                # per-call rule (phone_call / send_sms) are never
                # stamped.
                consent_digest = consent_digest_for(
                    vstep.tool, dict(vstep.args)
                )
                consent_source = CONSENT_PLAN_CARD
            steps.append(
                PlanStep(
                    step_id=step_id,
                    intent=vstep.intent,
                    tool=vstep.tool,
                    args=dict(vstep.args),
                    state=state,
                    depth=0,
                    parent_step_id=None,
                    idempotency_key=f"{plan_id}:{step_id}",
                    blocked_reason=blocked_reason,
                    verify=vstep.verify,
                    consent_digest=consent_digest,
                    consent_source=consent_source,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
            )

        plan = Plan(
            plan_id=plan_id,
            goal=request.goal,
            origin=request.origin,
            steps=steps,
            prior_actions=prior_actions,
            replans_used=0,
            awaiting_step_id=None,
            escalated=False,
            created_at=now_iso,
            updated_at=now_iso,
            expires_at=iso(
                now + timedelta(hours=PLAN_TTL_HOURS)
            ),
        )

        self._store.save(plan_to_record(plan, now))

        if ask_hits and self._notifier is not None:
            # Interactive disclosure (Decision 6): stated on
            # the notice, never asked, never a gate.
            self._notify_notices(plan, disclosure_lines(ask_hits))

        if self._notifier is not None:
            approval_steps = sum(
                1
                for s in steps
                if s.state is StepState.PENDING
                and s.tool in self._confirming_tools
                # Decision 7: a plan-consent-stamped step will
                # NOT ask when reached — counting it would make
                # the creation notice promise a card that never
                # comes.
                and s.consent_source != CONSENT_PLAN_CARD
            )
            self._notifier.created(plan, approval_steps)

        return CreatePlanOutcome(created=True, plan=plan)
