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
from app.privacy.services import dsr_execution_health
from app.privacy.services.dsr_execution_health import (
    get_privacy_dsr_execution_health,
)
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_dsr(
    session,
    *,
    execution_status: DataSubjectRequestExecutionStatus,
    now: datetime,
    old: datetime,
) -> DataSubjectRequest:
    dsr = DataSubjectRequest(
        request_type=DataSubjectRequestType.EXPORT.value,
        status=DataSubjectRequestStatus.APPROVED.value,
        execution_status=execution_status.value,
        submitted_at=old,
        due_at=now + timedelta(days=10),
        execution_completed_at=(
            old
            if execution_status
            in {
                DataSubjectRequestExecutionStatus.READY,
                DataSubjectRequestExecutionStatus.DELIVERED,
            }
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
    queued_at: datetime,
    expires_at: datetime,
    downloaded_at: datetime | None = None,
    download_count: int = 0,
) -> ExportArtifact:
    is_processing = status is ExportArtifactStatus.PROCESSING
    artifact = ExportArtifact(
        data_subject_request_id=dsr.id,
        status=status.value,
        format=ExportArtifactFormat.JSON_ZIP.value,
        storage_backend=ExportArtifactStorageBackend.LOCAL.value,
        schema_version="1.0",
        queued_at=queued_at,
        started_at=queued_at if is_processing else None,
        completed_at=queued_at if status is ExportArtifactStatus.READY else None,
        processing_token=str(uuid4()) if is_processing else None,
        processing_lease_expires_at=(
            queued_at + timedelta(minutes=5) if is_processing else None
        ),
        expires_at=expires_at,
        downloaded_at=downloaded_at,
        download_count=download_count,
    )
    session.add(artifact)
    await session.flush()
    return artifact


def test_privacy_dsr_execution_health_degrades_for_expired_ready_artifact(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            old = now - timedelta(hours=2)
            dsr = await _create_dsr(
                session,
                execution_status=DataSubjectRequestExecutionStatus.READY,
                now=now,
                old=old,
            )
            await _create_export_artifact(
                session,
                dsr=dsr,
                status=ExportArtifactStatus.READY,
                queued_at=old,
                expires_at=now - timedelta(minutes=1),
            )

            snapshot = await get_privacy_dsr_execution_health(
                session,
                now=now,
                stale_after=timedelta(hours=1),
                emit_metrics=False,
                emit_log=False,
            )

            assert snapshot.status == "degraded"
            assert snapshot.failed_export_artifacts == 0
            assert snapshot.stale_export_artifacts == 1
            assert snapshot.stale_export_artifact_counts["ready"] == 1

    run_async(_run())


def test_privacy_dsr_execution_health_ignores_delivered_expired_ready_artifact(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            old = now - timedelta(hours=2)
            dsr = await _create_dsr(
                session,
                execution_status=DataSubjectRequestExecutionStatus.DELIVERED,
                now=now,
                old=old,
            )
            await _create_export_artifact(
                session,
                dsr=dsr,
                status=ExportArtifactStatus.READY,
                queued_at=old,
                expires_at=now - timedelta(minutes=1),
                downloaded_at=old + timedelta(minutes=10),
                download_count=1,
            )

            snapshot = await get_privacy_dsr_execution_health(
                session,
                now=now,
                stale_after=timedelta(hours=1),
                emit_metrics=False,
                emit_log=False,
            )

            assert snapshot.status == "ok"
            assert snapshot.request_counts["export"]["delivered"] == 1
            assert snapshot.export_artifact_counts["ready"] == 1
            assert snapshot.stale_export_artifacts == 0
            assert snapshot.stale_export_artifact_counts["ready"] == 0

    run_async(_run())


def test_privacy_dsr_execution_health_ignores_superseded_expired_ready_artifact(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            old = now - timedelta(hours=2)
            recent = now - timedelta(minutes=5)
            dsr = await _create_dsr(
                session,
                execution_status=DataSubjectRequestExecutionStatus.READY,
                now=now,
                old=old,
            )
            await _create_export_artifact(
                session,
                dsr=dsr,
                status=ExportArtifactStatus.READY,
                queued_at=old,
                expires_at=now - timedelta(minutes=1),
            )
            await _create_export_artifact(
                session,
                dsr=dsr,
                status=ExportArtifactStatus.READY,
                queued_at=recent,
                expires_at=now + timedelta(days=1),
            )

            snapshot = await get_privacy_dsr_execution_health(
                session,
                now=now,
                stale_after=timedelta(hours=1),
                emit_metrics=False,
                emit_log=False,
            )

            assert snapshot.status == "ok"
            assert snapshot.export_artifact_counts["ready"] == 2
            assert snapshot.stale_export_artifacts == 0
            assert snapshot.stale_export_artifact_counts["ready"] == 0

    run_async(_run())


def test_privacy_dsr_health_stale_artifact_metrics_preserve_status() -> None:
    snapshot = dsr_execution_health.DsrExecutionHealthSnapshot(
        checked_at=datetime.now(UTC),
        status="degraded",
        stale_after_seconds=3600,
        stale_export_artifact_counts={"queued": 1, "processing": 2, "ready": 3},
        stale_export_artifacts=6,
    )

    stale_points = {
        point.execution_status: point.count
        for point in snapshot.to_metric_points()
        if point.job_kind == "export_artifact" and point.signal == "stale"
    }

    assert stale_points == {"queued": 1, "processing": 2, "ready": 3}
