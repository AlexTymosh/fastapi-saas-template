from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.services.dsr_execution_health import (
    get_privacy_dsr_execution_health,
)
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_dsr(
    session,
    *,
    request_type: DataSubjectRequestType,
    execution_status: DataSubjectRequestExecutionStatus,
    status: DataSubjectRequestStatus,
    now: datetime,
    old: datetime,
) -> DataSubjectRequest:
    is_active = execution_status in {
        DataSubjectRequestExecutionStatus.QUEUED,
        DataSubjectRequestExecutionStatus.PROCESSING,
    }
    dsr = DataSubjectRequest(
        request_type=request_type.value,
        status=status.value,
        execution_status=execution_status.value,
        submitted_at=old,
        due_at=now + timedelta(days=10),
        cancelled_at=now if status is DataSubjectRequestStatus.CANCELLED else None,
        execution_started_at=old if is_active else None,
        execution_failed_at=(
            old
            if execution_status is DataSubjectRequestExecutionStatus.FAILED
            else None
        ),
        created_at=old,
        updated_at=old,
    )
    session.add(dsr)
    await session.flush()
    return dsr


async def _create_export_artifact(
    session,
    *,
    dsr: DataSubjectRequest,
    status: ExportArtifactStatus,
    now: datetime,
    old: datetime,
) -> ExportArtifact:
    is_processing = status is ExportArtifactStatus.PROCESSING
    artifact = ExportArtifact(
        data_subject_request_id=dsr.id,
        status=status.value,
        format=ExportArtifactFormat.JSON_ZIP.value,
        storage_backend=ExportArtifactStorageBackend.LOCAL.value,
        schema_version="1.0",
        queued_at=old,
        started_at=old if is_processing else None,
        processing_token=str(uuid4()) if is_processing else None,
        processing_lease_expires_at=(
            now - timedelta(minutes=1) if is_processing else None
        ),
        failed_at=old if status is ExportArtifactStatus.FAILED else None,
        expires_at=now + timedelta(days=1),
    )
    session.add(artifact)
    await session.flush()
    return artifact


def test_privacy_dsr_execution_health_excludes_cancelled_dsr_work(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            old = now - timedelta(hours=2)
            cancelled_dsr = await _create_dsr(
                session,
                request_type=DataSubjectRequestType.EXPORT,
                execution_status=DataSubjectRequestExecutionStatus.PROCESSING,
                status=DataSubjectRequestStatus.CANCELLED,
                now=now,
                old=old,
            )
            await _create_export_artifact(
                session,
                dsr=cancelled_dsr,
                status=ExportArtifactStatus.PROCESSING,
                now=now,
                old=old - timedelta(minutes=1),
            )
            await _create_export_artifact(
                session,
                dsr=cancelled_dsr,
                status=ExportArtifactStatus.FAILED,
                now=now,
                old=old,
            )

            snapshot = await get_privacy_dsr_execution_health(
                session,
                now=now,
                stale_after=timedelta(hours=1),
                emit_metrics=False,
                emit_log=False,
            )

            assert snapshot.status == "ok"
            assert snapshot.total_dsr_jobs == 0
            assert snapshot.total_failed_dsr_jobs == 0
            assert snapshot.total_stale_dsr_jobs == 0
            assert snapshot.failed_export_artifacts == 0
            assert snapshot.stale_export_artifacts == 0
            assert snapshot.export_artifact_counts["failed"] == 1
            assert snapshot.export_artifact_counts["processing"] == 1

    run_async(_run())
