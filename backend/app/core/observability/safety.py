from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

from app.core.logging import get_logger

log = get_logger(__name__)

_LOG_SUPPRESSION_WINDOW_SECONDS: Final = 60.0
_last_metrics_failure_log_at: dict[tuple[str, str, str], float] = {}


def _should_log_failure(*, metric_name: str, metric_event: str, reason: str) -> bool:
    now = time.monotonic()
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
    if not _should_log_failure(
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


def safely_record_observability(
    operation: Callable[[], None],
    *,
    metric_name: str,
    metric_event: str,
    on_failure: Callable[[str, str, str], None] | None = None,
) -> None:
    try:
        operation()
    except Exception as exc:
        reason = exc.__class__.__name__
        if on_failure is not None:
            try:
                on_failure(metric_name, metric_event, reason)
            except Exception:
                pass
        _log_metrics_failure(
            metric_name=metric_name,
            metric_event=metric_event,
            reason=reason,
        )
