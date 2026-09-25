"""JSON-file task store: atomic writes, tolerant reads.

Lives under <base>/scheduler/tasks.json (runtime state, never
committed — like memory/memory.json). Writes go to a temp file
+ os.replace, so a crash can never leave a half-written store.
Corrupt files read as empty (logged to stderr); the daemon never
crashes on bad state.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from features.scheduler.application.dto.scheduler import TaskRecord
from features.scheduler.application.ports.task_store import (
    TaskStorePort,
)


def default_store_path() -> Path:
    return (
        Path.home() / "ALIX-Agent" / "scheduler" / "tasks.json"
    )


class JsonTaskStore(TaskStorePort):
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

    def load_tasks(self) -> List[TaskRecord]:
        try:
            raw = self._path.read_text(
                encoding="utf-8"
            )
        except FileNotFoundError:
            return []
        except OSError as exc:
            print(
                f"[scheduler] cannot read store: {exc}",
                file=sys.stderr,
            )
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(
                f"[scheduler] corrupt store, "
                f"treating as empty: {exc}",
                file=sys.stderr,
            )
            return []

        if not isinstance(data, list):
            print(
                "[scheduler] store is not a list, "
                "treating as empty",
                file=sys.stderr,
            )
            return []

        tasks: List[TaskRecord] = []

        for item in data:

            if not isinstance(item, dict):
                continue

            try:
                tasks.append(
                    TaskRecord.from_dict(item)
                )
            except (KeyError, TypeError, ValueError):
                continue

        return tasks

    def save_tasks(
        self,
        tasks: List[TaskRecord],
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = json.dumps(
            [t.to_dict() for t in tasks],
            ensure_ascii=False,
            indent=2,
        )

        fd, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".tasks-",
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
