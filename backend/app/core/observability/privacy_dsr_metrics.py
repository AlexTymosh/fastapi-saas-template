from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock
from typing import Final

from opentelemetry.metrics import CallbackOptions, Observation

from app.core.observability.metrics import meter
from app.core.observability.safety import (
    _handle_metric_recording_failure,
    _safe_record_metric,
)

PRIVACY_DSR_JOBS_GAUGE_NAME: Final = "privacy.dsr.jobs"
PRIVACY_DSR_HEALTH_CHECKS_TOTAL_NAME: Final = "privacy.dsr.health_checks.total"

PRIVACY_DSR_ATTRIBUTE_JOB_KIND: Final = "privacy.dsr.job_kind"
PRIVACY_DSR_ATTRIBUTE_REQUEST_TYPE: Final = "privacy.dsr.request_type"
PRIVACY_DSR_ATTRIBUTE_EXECUTION_STATUS: Final = "privacy.dsr.execution_status"
PRIVACY_DSR_ATTRIBUTE_SIGNAL: Final = "privacy.dsr.signal"
PRIVACY_DSR_ATTRIBUTE_HEALTH_STATUS: Final = "privacy.dsr.health_status"

ALLOWED_PRIVACY_DSR_JOB_KINDS: Final[frozenset[str]] = frozenset(
    {"dsr_request", "export_artifact"}
)
ALLOWED_PRIVACY_DSR_REQUEST_TYPES: Final[frozenset[str]] = frozenset(
    {"export", "erase"}
)
ALLOWED_PRIVACY_DSR_SIGNALS: Final[frozenset[str]] = frozenset(
    {"current", "failed", "stale"}
)
ALLOWED_PRIVACY_DSR_HEALTH_STATUSES: Final[frozenset[str]] = frozenset(
    {"ok", "degraded"}
)
ALLOWED_PRIVACY_DSR_JOB_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        PRIVACY_DSR_ATTRIBUTE_JOB_KIND,
        PRIVACY_DSR_ATTRIBUTE_REQUEST_TYPE,
        PRIVACY_DSR_ATTRIBUTE_EXECUTION_STATUS,
        PRIVACY_DSR_ATTRIBUTE_SIGNAL,
    }
)
ALLOWED_PRIVACY_DSR_HEALTH_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {PRIVACY_DSR_ATTRIBUTE_HEALTH_STATUS}
)

PrivacyDsrJobPointKey = tuple[str, str, str, str]


@dataclass(frozen=True, slots=True)
class PrivacyDsrMetricPoint:
    job_kind: str
    request_type: str
    execution_status: str
    signal: str
    count: int

    def attributes(self) -> dict[str, str]:
        return {
            PRIVACY_DSR_ATTRIBUTE_JOB_KIND: self.job_kind,
            PRIVACY_DSR_ATTRIBUTE_REQUEST_TYPE: self.request_type,
            PRIVACY_DSR_ATTRIBUTE_EXECUTION_STATUS: self.execution_status,
            PRIVACY_DSR_ATTRIBUTE_SIGNAL: self.signal,
        }


_last_privacy_dsr_job_points: dict[PrivacyDsrJobPointKey, int] = {}
_privacy_dsr_job_points_lock = RLock()


def _observe_privacy_dsr_jobs(
    options: CallbackOptions,
) -> Iterable[Observation]:
    del options
    with _privacy_dsr_job_points_lock:
        points_snapshot = tuple(sorted(_last_privacy_dsr_job_points.items()))

    for (
        job_kind,
        request_type,
        execution_status,
        signal,
    ), count in points_snapshot:
        yield Observation(
            count,
            attributes={
                PRIVACY_DSR_ATTRIBUTE_JOB_KIND: job_kind,
                PRIVACY_DSR_ATTRIBUTE_REQUEST_TYPE: request_type,
                PRIVACY_DSR_ATTRIBUTE_EXECUTION_STATUS: execution_status,
                PRIVACY_DSR_ATTRIBUTE_SIGNAL: signal,
            },
        )


privacy_dsr_health_checks_total = meter.create_counter(
    PRIVACY_DSR_HEALTH_CHECKS_TOTAL_NAME,
    unit="{check}",
    description="Total number of DSR execution health snapshots emitted.",
)

privacy_dsr_jobs = meter.create_observable_gauge(
    PRIVACY_DSR_JOBS_GAUGE_NAME,
    callbacks=[_observe_privacy_dsr_jobs],
    unit="{job}",
    description="Latest observed DSR execution job counts by low-cardinality state.",
)


def record_privacy_dsr_health_snapshot(
    *,
    status: str,
    points: Iterable[PrivacyDsrMetricPoint],
) -> None:
    global _last_privacy_dsr_job_points

    try:
        _validate_health_status(status)
        normalised_points = tuple(points)
        for point in normalised_points:
            _validate_metric_point(point)
    except Exception as exc:
        _handle_metric_recording_failure(
            metric_name=PRIVACY_DSR_JOBS_GAUGE_NAME,
            metric_event="privacy_dsr_health_snapshot",
            reason=exc.__class__.__name__,
        )
        return

    new_job_points = {
        (
            point.job_kind,
            point.request_type,
            point.execution_status,
            point.signal,
        ): point.count
        for point in normalised_points
    }
    with _privacy_dsr_job_points_lock:
        _last_privacy_dsr_job_points = new_job_points

    _safe_record_metric(
        privacy_dsr_health_checks_total.add,
        1,
        attributes={PRIVACY_DSR_ATTRIBUTE_HEALTH_STATUS: status},
        metric_name=PRIVACY_DSR_HEALTH_CHECKS_TOTAL_NAME,
        metric_event="privacy_dsr_health_snapshot",
    )


def _validate_metric_point(point: PrivacyDsrMetricPoint) -> None:
    _validate_attribute_keys(
        point.attributes(),
        ALLOWED_PRIVACY_DSR_JOB_ATTRIBUTE_KEYS,
    )
    if point.job_kind not in ALLOWED_PRIVACY_DSR_JOB_KINDS:
        raise ValueError(f"Unsupported DSR job kind: {point.job_kind}")
    if point.request_type not in ALLOWED_PRIVACY_DSR_REQUEST_TYPES:
        raise ValueError(f"Unsupported DSR request type: {point.request_type}")
    if point.signal not in ALLOWED_PRIVACY_DSR_SIGNALS:
        raise ValueError(f"Unsupported DSR metric signal: {point.signal}")
    if point.count < 0:
        raise ValueError("DSR metric point count must be non-negative")


def _validate_health_status(status: str) -> None:
    if status not in ALLOWED_PRIVACY_DSR_HEALTH_STATUSES:
        raise ValueError(f"Unsupported DSR health status: {status}")


def _validate_attribute_keys(
    attributes: dict[str, str | int],
    allowed_keys: frozenset[str],
) -> None:
    invalid_keys = set(attributes).difference(allowed_keys)
    if invalid_keys:
        keys = ", ".join(sorted(invalid_keys))
        raise ValueError(f"Unsupported metric attribute keys: {keys}")
