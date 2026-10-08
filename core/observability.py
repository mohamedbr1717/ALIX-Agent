from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.secret_scrub import SENSITIVE_KEYS as _UNIFIED_SENSITIVE_KEYS
from core.secret_scrub import scrub_value as _scrub_value


class ObservabilityLogger:
    """
    ALIX Observability Core V1.

    مسؤول عن:
    - Structured JSONL events
    - request/execution correlation IDs
    - timestamps
    - status and latency
    - recursive secret sanitization
    - bounded event persistence

    لا يقوم هذا الإصدار بعد بدمج Merkle integrity.
    """

    # Unified in core/secret_scrub.py (single source of truth).
    SENSITIVE_KEYS = _UNIFIED_SENSITIVE_KEYS

    def __init__(
        self,
        log_file: str | Path | None = None,
        max_value_length: int = 2000,
    ):
        self.log_file = Path(
            log_file
            if log_file is not None
            else Path.home()
            / "ALIX-Agent"
            / "logs"
            / "audit.jsonl"
        )

        self.max_value_length = max(
            128,
            int(max_value_length),
        )

        self.log_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def timestamp() -> str:
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    def sanitize(
        self,
        value: Any,
        *,
        key: str | None = None,
    ) -> Any:
        """
        Recursive sanitization.

        يمنع تسجيل الأسرار حتى لو كانت داخل:
        dict -> list -> dict -> ...
        Delegates to core/secret_scrub (single source of truth).
        """
        return _scrub_value(
            value, key=key, max_value_length=self.max_value_length
        )

    def emit(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        execution_id: str | None = None,
        status: str | None = None,
        latency_ms: float | None = None,
    ) -> dict[str, Any]:
        """
        ينشئ Event موحدًا ويحفظه كسطر JSON واحد.
        """

        if not isinstance(event, str) or not event.strip():
            raise ValueError("event must be a non-empty string")

        if data is None:
            data = {}

        if not isinstance(data, dict):
            raise TypeError("data must be a dictionary")

        record: dict[str, Any] = {
            "timestamp": self.timestamp(),
            "event": event,
            "request_id": (
                request_id
                if request_id is not None
                else self.new_id()
            ),
            "execution_id": execution_id,
            "status": status,
            "latency_ms": (
                round(float(latency_ms), 4)
                if latency_ms is not None
                else None
            ),
            "data": self.sanitize(data),
        }

        # لا نكرر الحقول التي لا تحمل قيمة.
        if execution_id is None:
            record.pop("execution_id")

        if status is None:
            record.pop("status")

        if latency_ms is None:
            record.pop("latency_ms")

        serialized = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
        )

        with self.log_file.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(serialized + "\n")

        return record

    def start_execution(
        self,
        event: str,
        *,
        request_id: str | None = None,
        execution_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[str, float, dict[str, Any]]:
        """
        يسجل بداية عملية ويعيد:
        execution_id, monotonic start time, event record
        """

        execution_id = (
            execution_id
            if execution_id is not None
            else self.new_id()
        )

        started = time.monotonic()

        record = self.emit(
            event,
            data,
            request_id=request_id,
            execution_id=execution_id,
            status="started",
        )

        return execution_id, started, record

    def finish_execution(
        self,
        event: str,
        *,
        started: float,
        request_id: str | None = None,
        execution_id: str | None = None,
        status: str = "success",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        يسجل نهاية العملية مع latency محسوبة من monotonic clock.
        """

        elapsed_ms = (
            time.monotonic() - started
        ) * 1000.0

        return self.emit(
            event,
            data,
            request_id=request_id,
            execution_id=execution_id,
            status=status,
            latency_ms=elapsed_ms,
        )
