from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.privacy.models.data_subject_request import DataSubjectRequest
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


async def _create_user_dsr_and_artifact(
    session,
    *,
    status: str,
    processing_lease_expires_at: datetime | None = None,
    processing_token: str | None = None,
):
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
    )
    session.add(user)
    await session.flush()

    dsr = DataSubjectRequest(
        request_type="export",
        status="approved",
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=datetime.now(UTC),
        due_at=datetime.now(UTC),
    )
    session.add(dsr)
    await session.flush()

    artifact = ExportArtifact(
        data_subject_request_id=dsr.id,
        requester_user_id=user.id,
        subject_user_id=user.id,
        status=status,
        format=ExportArtifactFormat.JSON_ZIP.value,
        storage_backend=ExportArtifactStorageBackend.LOCAL.value,
        schema_version="1.0",
        queued_at=datetime.now(UTC),
        started_at=datetime.now(UTC)
        if status == ExportArtifactStatus.PROCESSING.value
        else None,
        processing_token=processing_token,
        processing_lease_expires_at=processing_lease_expires_at,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(artifact)
    await session.flush()
    return artifact


def test_stale_processing_artifact_is_requeued(migrated_session_factory) -> None:
    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                artifact = await _create_user_dsr_and_artifact(
                    session,
                    status=ExportArtifactStatus.PROCESSING.value,
                    processing_token="stale-token",
                    processing_lease_expires_at=datetime.now(UTC)
                    - timedelta(seconds=1),
                )
                recovered = await ExportArtifactService(
                    session
                ).recover_stale_processing_artifacts(limit=10)

                assert recovered == 1
                assert artifact.status == ExportArtifactStatus.QUEUED.value
                assert artifact.started_at is None
                assert artifact.processing_token is None
                assert artifact.processing_lease_expires_at is None

    run_async(_run())


def test_recent_processing_artifact_is_not_requeued(migrated_session_factory) -> None:
    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                artifact = await _create_user_dsr_and_artifact(
                    session,
                    status=ExportArtifactStatus.PROCESSING.value,
                    processing_token="active-token",
                    processing_lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
                recovered = await ExportArtifactService(
                    session
                ).recover_stale_processing_artifacts(limit=10)

                assert recovered == 0
                assert artifact.status == ExportArtifactStatus.PROCESSING.value
                assert artifact.processing_token == "active-token"

    run_async(_run())


def test_claimed_artifact_gets_processing_token_and_lease(
    monkeypatch, migrated_session_factory
) -> None:
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                artifact = await _create_user_dsr_and_artifact(
                    session,
                    status=ExportArtifactStatus.QUEUED.value,
                )
                leases = await ExportArtifactService(
                    session
                ).claim_queued_artifact_leases(batch_size=10)

                assert len(leases) == 1
                assert leases[0].artifact_id == artifact.id
                assert leases[0].processing_token
                assert artifact.status == ExportArtifactStatus.PROCESSING.value
                assert artifact.processing_token == leases[0].processing_token
                assert artifact.processing_lease_expires_at is not None

    run_async(_run())


def test_stale_worker_cannot_mark_newer_lease_failed(
    monkeypatch, migrated_session_factory
) -> None:
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                artifact = await _create_user_dsr_and_artifact(
                    session,
                    status=ExportArtifactStatus.PROCESSING.value,
                    processing_token="new-token",
                    processing_lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
                service = ExportArtifactService(session)
                result = await service.mark_export_artifact_failed(
                    artifact_id=artifact.id,
                    exc=RuntimeError("old worker failed late"),
                    processing_token="old-token",
                )

                assert result is None
                assert artifact.status == ExportArtifactStatus.PROCESSING.value
                assert artifact.failure_reason_code is None
                assert artifact.processing_token == "new-token"

    run_async(_run())
