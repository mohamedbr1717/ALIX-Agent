"""Means log use case (Decision 4): derive, persist, advise.

The log is a DERIVED artifact — a JSON summary next to the
plan store, rebuilt from the stored plans whenever a plan
run finishes. It is never written on the hot path of a step,
it holds no argument values (only what PlanStep records
already hold: tool, state, verdict), and it can be deleted
and rebuilt at any time. Its consumers are the planner's
advisory context and the weekly self-diagnosis.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from domain.planning.means import (
    FAMILY_LABELS,
    aggregate_outcomes,
    best_tool_per_family,
)

from features.planning.application.mapping import record_to_plan
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)
from features.planning.application.use_cases.helpers import iso


class MeansLogUseCase:
    """Refresh + read the derived means log."""

    def __init__(
        self,
        *,
        store: PlanStorePort,
        path: Path,
        clock: Callable,
    ):
        self._store = store
        self._path = Path(path)
        self._clock = clock

    # ---------------------------------------------------------

    def refresh(self) -> dict:
        """Rebuild the log from the store and persist it."""
        now = self._clock()
        plans = [
            record_to_plan(record, now)
            for record in self._store.list_all()
        ]
        per_tool = aggregate_outcomes(plans)
        rows = sorted(
            per_tool.values(),
            key=lambda r: (r["family"], r["tool"]),
        )
        payload = {
            "version": 1,
            "refreshed_at": iso(now),
            "per_tool": rows,
            "best_per_family": best_tool_per_family(per_tool),
        }
        self._write(payload)
        return payload

    def hints(self) -> List[str]:
        """Advisory lines for the planner's context — the
        best verified means per family, from the log. Empty
        when the log is missing or unreadable: advice never
        blocks planning."""
        payload = self._read()
        if payload is None:
            return []
        per_tool = {
            (row["family"], row["tool"]): row
            for row in payload.get("per_tool", [])
        }
        lines: List[str] = []
        for family, tool in sorted(
            payload.get("best_per_family", {}).items()
        ):
            row = per_tool.get((family, tool), {})
            label = FAMILY_LABELS.get(family, family)
            lines.append(
                f"في عائلة {label}: أنجح وسيلة موثّقة هي "
                f"{tool} ({row.get('verified', 0)} نتيجة موثّقة، "
                f"{row.get('failed', 0)} فاشلة)."
            )
        return lines

    # ---------------------------------------------------------

    def _read(self) -> Optional[dict]:
        try:
            data = json.loads(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".means-",
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


def refresh_quietly(means_log: Optional[MeansLogUseCase]) -> None:
    """Refresh after a plan run. Telemetry must never break
    execution: a failed refresh is reported on stderr and
    otherwise ignored (the log is derived — the next refresh
    rebuilds it whole)."""
    if means_log is None:
        return
    try:
        means_log.refresh()
    except Exception as exc:  # noqa: BLE001 — telemetry guard
        print(
            f"[planning] means log refresh failed: {exc}",
            file=sys.stderr,
        )
