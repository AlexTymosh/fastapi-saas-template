from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

from app.core.logging import get_logger
from app.core.observability.metrics import meter

log = get_logger(__name__)

OBSERVABILITY_RECORDING_FAILURES_TOTAL_NAME: Final = (
    "observability.recording_failures.total"
)

OBSERVABILITY_ATTRIBUTE_METRIC_NAME: Final = "observability.metric_name"
OBSERVABILITY_ATTRIBUTE_METRIC_EVENT: Final = "observability.metric_event"
OBSERVABILITY_ATTRIBUTE_REASON: Final = "observability.reason"

_LOG_SUPPRESSION_WINDOW_SECONDS: Final = 60.0
_last_metrics_failure_log_at: dict[tuple[str, str, str], float] = {}

observability_recording_failures_total = meter.create_counter(
    OBSERVABILITY_RECORDING_FAILURES_TOTAL_NAME,
    unit="{failure}",
    description="Total number of observability metric recording failures.",
)


def _monotonic() -> float:
    return time.monotonic()


def _should_emit_failure_log(
    *, metric_name: str, metric_event: str, reason: str
) -> bool:
    now = _monotonic()
    key = (metric_name, metric_event, reason)
    last_logged_at = _last_metrics_failure_log_at.get(key)
    if (
        last_logged_at is None
        or now - last_logged_at >= _LOG_SUPPRESSION_WINDOW_SECONDS
    ):
        _last_metrics_failure_log_at[key] = now
        return True
    return False


def _log_metrics_failure(*, metric_name: str, metric_event: str, reason: str) -> None:
    if not _should_emit_failure_log(
        metric_name=metric_name,
        metric_event=metric_event,
        reason=reason,
    ):
        return

    try:
        log.warning(
            "metrics_recording_failed",
            metric_name=metric_name,
            metric_event=metric_event,
            reason=reason,
            category="observability",
        )
    except Exception:
        return


def _record_observability_failure_metric(
    *, metric_name: str, metric_event: str, reason: str
) -> None:
    if metric_name == OBSERVABILITY_RECORDING_FAILURES_TOTAL_NAME:
        return

    try:
        observability_recording_failures_total.add(
            1,
            attributes={
                OBSERVABILITY_ATTRIBUTE_METRIC_NAME: metric_name,
                OBSERVABILITY_ATTRIBUTE_METRIC_EVENT: metric_event,
                OBSERVABILITY_ATTRIBUTE_REASON: reason,
            },
        )
    except Exception:
        return


def _handle_metric_recording_failure(
    *, metric_name: str, metric_event: str, reason: str
) -> None:
    _record_observability_failure_metric(
        metric_name=metric_name,
        metric_event=metric_event,
        reason=reason,
    )
    _log_metrics_failure(
        metric_name=metric_name, metric_event=metric_event, reason=reason
    )


def _safe_record_metric(
    operation: Callable[..., None],
    *args: object,
    metric_name: str,
    metric_event: str,
    **kwargs: object,
) -> None:
    try:
        operation(*args, **kwargs)
    except Exception as exc:
        _handle_metric_recording_failure(
            metric_name=metric_name,
            metric_event=metric_event,
            reason=exc.__class__.__name__,
        )
