"""JSON-file ask ledger (single-ask principle, 2026-11-01).

Lives next to plans.json as asked_clarifications.json:
{clarification_key: iso_timestamp}. Atomic writes through a
temp file + os.replace (the plan store's discipline);
corrupt or missing state reads as "never asked" and records
degrade silently — bookkeeping must never break creation.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from features.planning.application.ports.ask_ledger import (
    AskLedgerPort,
)
from features.planning.infrastructure.adapters.json_plan_store import (
    default_store_path,
)


def default_ledger_path() -> Path:
    return default_store_path().parent / "asked_clarifications.json"


class JsonAskLedger(AskLedgerPort):
    def __init__(self, path: Optional[Path] = None):
        self._path = (
            Path(path) if path is not None else default_ledger_path()
        )

    def _load(self) -> dict:
        try:
            data = json.loads(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def last_asked(self, key: str) -> Optional[datetime]:
        raw = self._load().get(key)
        if not isinstance(raw, str):
            return None
        try:
            when = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return when if when.tzinfo is not None else None

    def record(self, key: str, when: datetime) -> None:
        try:
            data = self._load()
            data[key] = when.isoformat()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self._path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as exc:  # bookkeeping never breaks creation
            print(
                f"ask ledger record failed: {exc}",
                file=sys.stderr,
            )
