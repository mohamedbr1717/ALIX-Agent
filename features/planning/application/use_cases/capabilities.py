"""Capability ledger use case (Decision 5).

Builds the derived ledger — declared facts plus cheap,
side-effect-free probes — persists it next to the plan store
as capabilities.json (same derived-artifact discipline as
the Decision-4 means log: rebuildable, never written on a
step's hot path), and serves its two consumers:

- the planner's view: which tools are unavailable HERE
  (excluded from the draft context, and rejected if drafted
  anyway), plus honest note lines;
- the executor's pre-flight: a step whose tool is
  unavailable never dispatches — it blocks as a capability
  fact, not a means failure.

Probes are local only: PATH lookups, environment presence
(names, never values), and the LLM router's own status
report. No network, no test calls, no side effects.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from domain.planning.capabilities import (
    AVAILABLE,
    DECLARED_STATES,
    LLM_LOCAL,
    LLM_REMOTE,
    SOURCE_DECLARED,
    SOURCE_PROBED,
    TOOL_REQUIREMENTS,
    UNAVAILABLE,
    UNKNOWN,
)

from features.planning.application.use_cases.helpers import iso

#: A probed state may be served from cache this long; the
#: ledger is refreshed at boot and (when stale) at plan
#: creation — the owner's derivation ruling.
REFRESH_TTL_SECONDS = 300


class CapabilitiesUseCase:
    """Refresh + read the derived capability ledger."""

    def __init__(
        self,
        *,
        path: Path,
        clock: Callable,
        binary_prober: Optional[Callable] = None,
        env_reader: Optional[Callable] = None,
        llm_status_provider: Optional[Callable] = None,
    ):
        self._path = Path(path)
        self._clock = clock
        self._which = binary_prober or shutil.which
        self._env = env_reader or os.environ.get
        self._llm_status = llm_status_provider
        self._payload: Optional[dict] = None
        self._refreshed_epoch: float = 0.0

    # ---------------------------------------------------------

    def refresh(self, force: bool = False) -> dict:
        """Rebuild the ledger from declarations + probes."""
        now = self._clock()
        epoch = now.timestamp()
        if (
            not force
            and self._payload is not None
            and epoch - self._refreshed_epoch < REFRESH_TTL_SECONDS
        ):
            return self._payload
        subjects = []
        for tool, requirement in sorted(TOOL_REQUIREMENTS.items()):
            state, evidence = self._probe(requirement)
            subjects.append({
                "subject": tool,
                "kind": "tool",
                "state": state,
                "source": SOURCE_PROBED,
                "evidence": evidence,
            })
        for tool, (state, evidence) in sorted(
            DECLARED_STATES.items()
        ):
            subjects.append({
                "subject": tool,
                "kind": "tool",
                "state": state,
                "source": SOURCE_DECLARED,
                "evidence": evidence,
            })
        subjects.extend(self._llm_subjects())
        payload = {
            "version": 1,
            "refreshed_at": iso(now),
            "subjects": subjects,
        }
        self._write(payload)
        self._payload = payload
        self._refreshed_epoch = epoch
        return payload

    def state_for(self, tool: str) -> Optional[Tuple[str, str]]:
        """(state, evidence) for a tool, or None when the
        ledger makes no claim about it. Absence of a claim is
        not a claim of availability."""
        if self._payload is None:
            self.refresh()
        for row in self._payload["subjects"]:
            if row["kind"] == "tool" and row["subject"] == tool:
                return row["state"], row["evidence"]
        return None

    def planner_view(self) -> Tuple[frozenset, List[str]]:
        """(excluded tools, note lines) for plan creation.

        Excluded = state unavailable (probed or declared);
        the planner never sees them as available means. Notes
        carry every non-available subject plus the LLM legs,
        as data for the draft."""
        payload = self.refresh()
        excluded = frozenset(
            row["subject"]
            for row in payload["subjects"]
            if row["kind"] == "tool" and row["state"] == UNAVAILABLE
        )
        notes: List[str] = []
        for row in payload["subjects"]:
            if row["state"] == AVAILABLE and row["kind"] == "tool":
                continue
            notes.append(
                f"{row['subject']}: {row['state']} — "
                f"{row['evidence']}"
            )
        return excluded, notes

    # ---------------------------------------------------------

    def _probe(self, requirement) -> Tuple[str, str]:
        kind, param = requirement
        if kind == "termux_binary":
            if self._which(param):
                return AVAILABLE, f"{param} موجود في PATH"
            return (
                UNAVAILABLE,
                f"{param} غير موجود — Termux:API غير متاح "
                "في هذا السياق",
            )
        if kind == "env_groups":
            full = sum(
                1
                for group in param
                if all((self._env(name) or "").strip()
                       for name in group)
            )
            if full:
                return (
                    AVAILABLE,
                    f"{full} من {len(param)} مجموعة بيانات "
                    "اعتماد مُهيّأة (الحضور فقط، لا القيم)",
                )
            return (
                UNAVAILABLE,
                "لا مجموعة بيانات اعتماد مُهيّأة في البيئة",
            )
        return UNKNOWN, f"نوع متطلب غير معروف: {kind}"

    def _llm_subjects(self) -> List[dict]:
        rows = []
        status = None
        if self._llm_status is not None:
            try:
                status = self._llm_status()
            except Exception:
                status = None
        if not isinstance(status, dict):
            for subject in (LLM_REMOTE, LLM_LOCAL):
                rows.append({
                    "subject": subject,
                    "kind": "subsystem",
                    "state": UNKNOWN,
                    "source": SOURCE_PROBED,
                    "evidence": "تعذّرت قراءة حالة موجّه النماذج",
                })
            return rows
        if status.get("remote_enabled") and status.get(
            "remote_configured"
        ):
            rows.append({
                "subject": LLM_REMOTE,
                "kind": "subsystem",
                "state": AVAILABLE,
                "source": SOURCE_PROBED,
                "evidence": (
                    f"مُهيّأ ومفعّل حسب تقرير الموجّه "
                    f"({status.get('remote_provider')}/"
                    f"{status.get('remote_model')})؛ الوصول "
                    "الفعلي غير مفحوص"
                ),
            })
        else:
            rows.append({
                "subject": LLM_REMOTE,
                "kind": "subsystem",
                "state": UNAVAILABLE,
                "source": SOURCE_PROBED,
                "evidence": "الرجل البعيدة معطّلة أو بلا مفتاح "
                            "مُهيّأ حسب تقرير الموجّه",
            })
        rows.append({
            "subject": LLM_LOCAL,
            "kind": "subsystem",
            "state": UNKNOWN,
            "source": SOURCE_PROBED,
            "evidence": (
                f"نقطة محلية مُهيّأة "
                f"({status.get('local_url')}/"
                f"{status.get('local_model')})؛ الحيوية غير "
                "مفحوصة في هذا الإصدار"
            ),
        })
        return rows

    # ---------------------------------------------------------

    def _write(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".capabilities-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self._path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def refresh_quietly(capabilities: Optional[CapabilitiesUseCase],
                    force: bool = False) -> None:
    """Refresh without ever breaking the caller: the ledger
    is derived state, and a failed rebuild leaves the last
    good payload (or no claim at all) in place."""
    if capabilities is None:
        return
    try:
        capabilities.refresh(force=force)
    except Exception as exc:  # noqa: BLE001 — telemetry guard
        print(
            f"[planning] capabilities refresh failed: {exc}",
            file=sys.stderr,
        )
