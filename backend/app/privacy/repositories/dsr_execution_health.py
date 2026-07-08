from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import ExportArtifact, ExportArtifactStatus


class DsrExecutionHealthRepository:
    """Read-model repository for aggregate DSR execution health queries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_dsr_requests_by_status(
        self,
        *,
        request_types: tuple[str, ...],
        execution_statuses: tuple[str, ...],
    ) -> dict[str, dict[str, int]]:
        counts = _empty_request_counts(
            request_types=request_types,
            execution_statuses=execution_statuses,
        )
        stmt = (
            select(
                DataSubjectRequest.request_type,
                DataSubjectRequest.execution_status,
                func.count(),
            )
            .where(
                DataSubjectRequest.request_type.in_(request_types),
                _non_cancelled_dsr_predicate(),
            )
            .group_by(
                DataSubjectRequest.request_type,
                DataSubjectRequest.execution_status,
            )
        )
        for request_type, execution_status, count in await self.session.execute(stmt):
            counts[str(request_type)][str(execution_status)] = int(count)
        return counts

    async def count_stale_dsr_requests_by_status(
        self,
        *,
        request_types: tuple[str, ...],
        stale_statuses: tuple[str, ...],
        checked_at: datetime,
        stale_cutoff: datetime,
    ) -> dict[str, dict[str, int]]:
        counts = _empty_request_counts(
            request_types=request_types,
            execution_statuses=stale_statuses,
        )
        stale_since = func.coalesce(
            DataSubjectRequest.execution_started_at,
            DataSubjectRequest.updated_at,
            DataSubjectRequest.created_at,
        )
        active_export_processing_lease = (
            select(ExportArtifact.id)
            .where(
                ExportArtifact.data_subject_request_id == DataSubjectRequest.id,
                ExportArtifact.status == ExportArtifactStatus.PROCESSING.value,
                ExportArtifact.processing_lease_expires_at.is_not(None),
                ExportArtifact.processing_lease_expires_at > checked_at,
            )
            .exists()
        )
        not_active_export_processing = or_(
            DataSubjectRequest.request_type != DataSubjectRequestType.EXPORT.value,
            DataSubjectRequest.execution_status
            != DataSubjectRequestExecutionStatus.PROCESSING.value,
            ~active_export_processing_lease,
        )
        stmt = (
            select(
                DataSubjectRequest.request_type,
                DataSubjectRequest.execution_status,
                func.count(),
            )
            .where(
                DataSubjectRequest.request_type.in_(request_types),
                DataSubjectRequest.execution_status.in_(stale_statuses),
                _non_cancelled_dsr_predicate(),
                stale_since <= stale_cutoff,
                not_active_export_processing,
            )
            .group_by(
                DataSubjectRequest.request_type,
                DataSubjectRequest.execution_status,
            )
        )
        for request_type, execution_status, count in await self.session.execute(stmt):
            counts[str(request_type)][str(execution_status)] = int(count)
        return counts

    async def count_export_artifacts_by_status(self) -> dict[str, int]:
        counts = {status.value: 0 for status in ExportArtifactStatus}
        stmt = select(ExportArtifact.status, func.count()).group_by(
            ExportArtifact.status
        )
        for artifact_status, count in await self.session.execute(stmt):
            counts[str(artifact_status)] = int(count)
        return counts

    async def count_current_failed_export_artifacts(self) -> int:
        newer_artifact = aliased(ExportArtifact)
        newer_for_same_dsr = (
            select(newer_artifact.id)
            .where(
                newer_artifact.data_subject_request_id
                == ExportArtifact.data_subject_request_id,
                or_(
                    newer_artifact.queued_at > ExportArtifact.queued_at,
                    and_(
                        newer_artifact.queued_at == ExportArtifact.queued_at,
                        newer_artifact.created_at > ExportArtifact.created_at,
                    ),
                ),
            )
            .exists()
        )
        stmt = (
            select(func.count())
            .select_from(ExportArtifact)
            .where(
                ExportArtifact.status == ExportArtifactStatus.FAILED.value,
                _non_cancelled_export_dsr_exists(),
                ~newer_for_same_dsr,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_stale_export_artifacts(
        self,
        *,
        checked_at: datetime,
        stale_cutoff: datetime,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ExportArtifact)
            .where(
                _non_cancelled_export_dsr_exists(),
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
                ),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())


def _non_cancelled_dsr_predicate() -> ColumnElement[bool]:
    return DataSubjectRequest.status != DataSubjectRequestStatus.CANCELLED.value


def _non_cancelled_export_dsr_exists() -> ColumnElement[bool]:
    return (
        select(DataSubjectRequest.id)
        .where(
            DataSubjectRequest.id == ExportArtifact.data_subject_request_id,
            DataSubjectRequest.request_type == DataSubjectRequestType.EXPORT.value,
            _non_cancelled_dsr_predicate(),
        )
        .exists()
    )


def _empty_request_counts(
    *,
    request_types: tuple[str, ...],
    execution_statuses: tuple[str, ...],
) -> dict[str, dict[str, int]]:
    return {
        request_type: {execution_status: 0 for execution_status in execution_statuses}
        for request_type in request_types
    }
