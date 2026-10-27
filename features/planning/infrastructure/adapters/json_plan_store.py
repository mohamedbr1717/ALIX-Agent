"""JSON-file plan store: atomic writes, tolerant reads.

Lives under <base>/planning/plans.json (runtime state, never
committed — like scheduler/tasks.json). The file holds a JSON
list of plan records. Every save rewrites the whole list through
a temp file + fsync + os.replace (JsonTaskStore's exact
discipline), so a crash can never leave a half-written store.
Corrupt state reads as empty (logged to stderr); the store never
crashes its caller on bad state.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from features.planning.application.dto.planning import PlanRecord
from features.planning.application.ports.plan_store import (
    PlanStorePort,
)


def default_store_path() -> Path:
    return (
        Path.home() / "ALIX-Agent" / "planning" / "plans.json"
    )


class JsonPlanStore(PlanStorePort):
    def __init__(
        self,
        path: Optional[Path] = None,
    ):
        self._path = (
            Path(path)
            if path is not None
            else default_store_path()
        )

    @property
    def path(self) -> Path:
        return self._path

    # ---------------------------------------------------------
    # PlanStorePort
    # ---------------------------------------------------------

    def save(self, record: PlanRecord) -> None:
        records = self._load_records()
        for index, existing in enumerate(records):
            if existing.plan_id == record.plan_id:
                records[index] = record
                break
        else:
            records.append(record)
        self._write_records(records)

    def get(self, plan_id: str) -> Optional[PlanRecord]:
        for record in self._load_records():
            if record.plan_id == plan_id:
                return record
        return None

    def list_all(self) -> List[PlanRecord]:
        return self._load_records()

    # ---------------------------------------------------------
    # File discipline (mirrors JsonTaskStore verbatim)
    # ---------------------------------------------------------

    def _load_records(self) -> List[PlanRecord]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            print(
                f"[planning] cannot read store: {exc}",
                file=sys.stderr,
            )
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(
                f"[planning] corrupt store, "
                f"treating as empty: {exc}",
                file=sys.stderr,
            )
            return []

        if not isinstance(data, list):
            print(
                "[planning] store is not a list, "
                "treating as empty",
                file=sys.stderr,
            )
            return []

        records: List[PlanRecord] = []

        for item in data:

            if not isinstance(item, dict):
                continue

            try:
                records.append(PlanRecord.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue

        return records

    def _write_records(
        self,
        records: List[PlanRecord],
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = json.dumps(
            [r.to_dict() for r in records],
            ensure_ascii=False,
            indent=2,
        )

        fd, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".plans-",
            suffix=".tmp",
        )

        try:

            with os.fdopen(
                fd, "w", encoding="utf-8"
            ) as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())

            os.replace(tmp_name, self._path)

        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
