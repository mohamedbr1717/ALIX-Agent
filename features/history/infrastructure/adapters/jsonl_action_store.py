"""JSON-lines action store (append-only, atomic writes)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class JsonlActionStore:
    """Stores actions in history/actions.jsonl (outside git)."""

    def __init__(self, path=None):
        if path is None:
            path = Path.home() / "ALIX-Agent" / "history" / "actions.jsonl"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def append(self, record: dict) -> None:
        entry = {
            "tool_name": record.get("tool_name", ""),
            "arguments": record.get("arguments", {}),
            "timestamp": record.get("timestamp") or self._now_iso(),
            "ok": bool(record.get("ok", False)),
            "summary": record.get("summary", ""),
            "inverse": record.get("inverse"),
            "undone": False,
        }
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(entry, ensure_ascii=False) + "\n"
                )
        except OSError:
            pass  # History failure must never break the agent.

    def list_recent(self, limit: int) -> list[dict]:
        try:
            lines = self._path.read_text(
                encoding="utf-8"
            ).splitlines()
        except OSError:
            return []
        records = []
        for line in lines[-max(1, limit) :]:
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
        return list(reversed(records))

    def mark_undone(self, index: int) -> bool:
        """Mark by reverse index (0 = most recent)."""
        try:
            lines = self._path.read_text(
                encoding="utf-8"
            ).splitlines()
        except OSError:
            return False
        if not lines or index < 0 or index >= len(lines):
            return False
        target = len(lines) - 1 - index
        try:
            record = json.loads(lines[target])
        except (json.JSONDecodeError, ValueError):
            return False
        record["undone"] = True
        lines[target] = json.dumps(record, ensure_ascii=False)
        # Atomic rewrite.
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), text=True
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, self._path)
            return True
        except OSError:
            return False
