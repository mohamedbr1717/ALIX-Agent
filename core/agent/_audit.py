"""ALIXAgent _AuditMixin (private)."""
from __future__ import annotations

from typing import Any
class _AuditMixin:
    """Methods moved verbatim."""

    def audit(
        self,
        event: str,
        data: dict[str, Any],
        *,
        request_id: str | None = None,
        execution_id: str | None = None,
        status: str | None = None,
        latency_ms: float | None = None,
    ):
        """
        Compatibility wrapper لـ Observability Core.

        يحافظ على واجهة audit() الحالية
        مع توحيد التسجيل عبر ObservabilityLogger.
        """

        try:
            return self.observability.emit(
                event,
                data,
                request_id=(
                    request_id
                    if request_id is not None
                    else self.current_request_id
                ),
                execution_id=execution_id,
                status=status,
                latency_ms=latency_ms,
            )
        except Exception:
            # فشل الـ logging لا يجب أن يوقف ALIX.
            return None


