from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LogCategory, get_logger
from app.core.observability.privacy_dsr_metrics import (
    PrivacyDsrMetricPoint,
    record_privacy_dsr_health_snapshot,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import ExportArtifact, ExportArtifactStatus

log = get_logger(__name__)

DEFAULT_DSR_STALE_AFTER = timedelta(hours=1)
_DSR_JOB_REQUEST_TYPES = (
    DataSubjectRequestType.EXPORT.value,
    DataSubjectRequestType.ERASE.value,
)
_STALE_DSR_STATUSES = (
    DataSubjectRequestExecutionStatus.QUEUED.value,
    DataSubjectRequestExecutionStatus.PROCESSING.value,
)
_FAILED_DSR_STATUSES = (
    DataSubjectRequestExecutionStatus.FAILED.value,
    DataSubjectRequestExecutionStatus.PARTIALLY_FULFILLED.value,
)


@dataclass(frozen=True, slots=True)
class DsrExecutionHealthSnapshot:
    checked_at: datetime
    status: str
    stale_after_seconds: int
    request_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    stale_request_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    failed_request_counts: dict[str, int] = field(default_factory=dict)
    export_artifact_counts: dict[str, int] = field(default_factory=dict)
    stale_export_artifacts: int = 0
    failed_export_artifacts: int = 0

    @property
    def total_dsr_jobs(self) -> int:
        return sum(sum(statuses.values()) for statuses in self.request_counts.values())

    @property
    def total_failed_dsr_jobs(self) -> int:
        return sum(self.failed_request_counts.values())

    @property
    def total_stale_dsr_jobs(self) -> int:
        return sum(
            sum(statuses.values()) for statuses in self.stale_request_counts.values()
        )

    @property
    def is_degraded(self) -> bool:
        return (
            self.total_failed_dsr_jobs > 0
            or self.total_stale_dsr_jobs > 0
            or self.failed_export_artifacts > 0
            or self.stale_export_artifacts > 0
        )

    def as_log_extra(self) -> dict[str, object]:
        return {
            "category": LogCategory.APPLICATION.value,
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
            "stale_after_seconds": self.stale_after_seconds,
            "total_dsr_jobs": self.total_dsr_jobs,
            "failed_dsr_jobs": self.total_failed_dsr_jobs,
            "stale_dsr_jobs": self.total_stale_dsr_jobs,
            "queued_dsr_jobs": self._count_dsr_status(
                DataSubjectRequestExecutionStatus.QUEUED.value
            ),
            "processing_dsr_jobs": self._count_dsr_status(
                DataSubjectRequestExecutionStatus.PROCESSING.value
            ),
            "ready_dsr_jobs": self._count_dsr_status(
                DataSubjectRequestExecutionStatus.READY.value
            ),
            "delivered_dsr_jobs": self._count_dsr_status(
                DataSubjectRequestExecutionStatus.DELIVERED.value
            ),
            "failed_export_artifacts": self.failed_export_artifacts,
            "stale_export_artifacts": self.stale_export_artifacts,
        }

    def to_metric_points(self) -> tuple[PrivacyDsrMetricPoint, ...]:
        points: list[PrivacyDsrMetricPoint] = []
        for request_type, statuses in sorted(self.request_counts.items()):
            for execution_status, count in sorted(statuses.items()):
                points.append(
                    PrivacyDsrMetricPoint(
                        job_kind="dsr_request",
                        request_type=request_type,
                        execution_status=execution_status,
                        signal="current",
                        count=count,
                    )
                )
        for request_type, statuses in sorted(self.stale_request_counts.items()):
            for execution_status, count in sorted(statuses.items()):
                points.append(
                    PrivacyDsrMetricPoint(
                        job_kind="dsr_request",
                        request_type=request_type,
                        execution_status=execution_status,
                        signal="stale",
                        count=count,
                    )
                )
        for request_type, count in sorted(self.failed_request_counts.items()):
            points.append(
                PrivacyDsrMetricPoint(
                    job_kind="dsr_request",
                    request_type=request_type,
                    execution_status=DataSubjectRequestExecutionStatus.FAILED.value,
                    signal="failed",
                    count=count,
                )
            )
        for artifact_status, count in sorted(self.export_artifact_counts.items()):
            points.append(
                PrivacyDsrMetricPoint(
                    job_kind="export_artifact",
                    request_type=DataSubjectRequestType.EXPORT.value,
                    execution_status=artifact_status,
                    signal="current",
                    count=count,
                )
            )
        points.extend(
            [
                PrivacyDsrMetricPoint(
                    job_kind="export_artifact",
                    request_type=DataSubjectRequestType.EXPORT.value,
                    execution_status=ExportArtifactStatus.PROCESSING.value,
                    signal="stale",
                    count=self.stale_export_artifacts,
                ),
                PrivacyDsrMetricPoint(
                    job_kind="export_artifact",
                    request_type=DataSubjectRequestType.EXPORT.value,
                    execution_status=ExportArtifactStatus.FAILED.value,
                    signal="failed",
                    count=self.failed_export_artifacts,
                ),
            ]
        )
        return tuple(points)

    def _count_dsr_status(self, execution_status: str) -> int:
        return sum(
            statuses.get(execution_status, 0)
            for statuses in self.request_counts.values()
        )


async def get_privacy_dsr_execution_health(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_DSR_STALE_AFTER,
    emit_metrics: bool = True,
    emit_log: bool = True,
) -> DsrExecutionHealthSnapshot:
    if stale_after.total_seconds() <= 0:
        raise ValueError("DSR execution stale_after must be positive")

    checked_at = _normalise_utc(now)
    stale_cutoff = checked_at - stale_after
    request_counts = await _count_dsr_requests_by_status(session)
    stale_request_counts = await _count_stale_dsr_requests_by_status(
        session,
        stale_cutoff=stale_cutoff,
    )
    failed_request_counts = _failed_counts_from_request_counts(request_counts)
    export_artifact_counts = await _count_export_artifacts_by_status(session)
    stale_export_artifacts = await _count_stale_export_artifacts(
        session,
        checked_at=checked_at,
        stale_cutoff=stale_cutoff,
    )
    failed_export_artifacts = export_artifact_counts.get(
        ExportArtifactStatus.FAILED.value,
        0,
    )
    snapshot = DsrExecutionHealthSnapshot(
        checked_at=checked_at,
        status="degraded",
        stale_after_seconds=int(stale_after.total_seconds()),
        request_counts=request_counts,
        stale_request_counts=stale_request_counts,
        failed_request_counts=failed_request_counts,
        export_artifact_counts=export_artifact_counts,
        stale_export_artifacts=stale_export_artifacts,
        failed_export_artifacts=failed_export_artifacts,
    )
    if not snapshot.is_degraded:
        snapshot = DsrExecutionHealthSnapshot(
            checked_at=snapshot.checked_at,
            status="ok",
            stale_after_seconds=snapshot.stale_after_seconds,
            request_counts=snapshot.request_counts,
            stale_request_counts=snapshot.stale_request_counts,
            failed_request_counts=snapshot.failed_request_counts,
            export_artifact_counts=snapshot.export_artifact_counts,
            stale_export_artifacts=snapshot.stale_export_artifacts,
            failed_export_artifacts=snapshot.failed_export_artifacts,
        )
    if emit_metrics:
        record_privacy_dsr_health_snapshot(
            status=snapshot.status,
            points=snapshot.to_metric_points(),
        )
    if emit_log:
        _log_dsr_execution_health(snapshot)
    return snapshot


async def _count_dsr_requests_by_status(
    session: AsyncSession,
) -> dict[str, dict[str, int]]:
    counts = _empty_request_counts()
    stmt = (
        select(
            DataSubjectRequest.request_type,
            DataSubjectRequest.execution_status,
            func.count(),
        )
        .where(DataSubjectRequest.request_type.in_(_DSR_JOB_REQUEST_TYPES))
        .group_by(
            DataSubjectRequest.request_type,
            DataSubjectRequest.execution_status,
        )
    )
    for request_type, execution_status, count in (await session.execute(stmt)).all():
        counts[str(request_type)][str(execution_status)] = int(count)
    return counts


async def _count_stale_dsr_requests_by_status(
    session: AsyncSession,
    *,
    stale_cutoff: datetime,
) -> dict[str, dict[str, int]]:
    counts = _empty_request_counts(statuses=_STALE_DSR_STATUSES)
    stale_since = func.coalesce(
        DataSubjectRequest.execution_started_at,
        DataSubjectRequest.updated_at,
        DataSubjectRequest.created_at,
    )
    stmt = (
        select(
            DataSubjectRequest.request_type,
            DataSubjectRequest.execution_status,
            func.count(),
        )
        .where(
            DataSubjectRequest.request_type.in_(_DSR_JOB_REQUEST_TYPES),
            DataSubjectRequest.execution_status.in_(_STALE_DSR_STATUSES),
            stale_since <= stale_cutoff,
        )
        .group_by(
            DataSubjectRequest.request_type,
            DataSubjectRequest.execution_status,
        )
    )
    for request_type, execution_status, count in (await session.execute(stmt)).all():
        counts[str(request_type)][str(execution_status)] = int(count)
    return counts


async def _count_export_artifacts_by_status(session: AsyncSession) -> dict[str, int]:
    counts = {status.value: 0 for status in ExportArtifactStatus}
    stmt = select(ExportArtifact.status, func.count()).group_by(ExportArtifact.status)
    for artifact_status, count in (await session.execute(stmt)).all():
        counts[str(artifact_status)] = int(count)
    return counts


async def _count_stale_export_artifacts(
    session: AsyncSession,
    *,
    checked_at: datetime,
    stale_cutoff: datetime,
) -> int:
    stmt = (
        select(func.count())
        .select_from(ExportArtifact)
        .where(
            or_(
                and_(
                    ExportArtifact.status == ExportArtifactStatus.QUEUED.value,
                    ExportArtifact.queued_at <= stale_cutoff,
                ),
                and_(
                    ExportArtifact.status == ExportArtifactStatus.PROCESSING.value,
                    ExportArtifact.processing_lease_expires_at.is_not(None),
                    ExportArtifact.processing_lease_expires_at <= checked_at,
                ),
                and_(
                    ExportArtifact.status == ExportArtifactStatus.PROCESSING.value,
                    ExportArtifact.processing_lease_expires_at.is_(None),
                    ExportArtifact.started_at <= stale_cutoff,
                ),
            )
        )
    )
    return int((await session.execute(stmt)).scalar_one())


def _empty_request_counts(
    *, statuses: tuple[str, ...] | None = None
) -> dict[str, dict[str, int]]:
    selected_statuses = statuses or tuple(
        status.value for status in DataSubjectRequestExecutionStatus
    )
    return {
        request_type: {execution_status: 0 for execution_status in selected_statuses}
        for request_type in _DSR_JOB_REQUEST_TYPES
    }


def _failed_counts_from_request_counts(
    request_counts: dict[str, dict[str, int]],
) -> dict[str, int]:
    return {
        request_type: sum(statuses.get(status, 0) for status in _FAILED_DSR_STATUSES)
        for request_type, statuses in request_counts.items()
    }


def _log_dsr_execution_health(snapshot: DsrExecutionHealthSnapshot) -> None:
    log_method = log.warning if snapshot.is_degraded else log.info
    log_method(
        "privacy_dsr_execution_health_checked",
        **snapshot.as_log_extra(),
    )


def _normalise_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("DSR execution health reference time must be timezone-aware")
    return value.astimezone(UTC)
