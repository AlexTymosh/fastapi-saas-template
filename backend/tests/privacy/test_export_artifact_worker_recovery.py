from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.commands.privacy_export_worker import run_worker
from app.core.config.settings import get_settings
from app.privacy.models.data_subject_request import DataSubjectRequest
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


def test_worker_reclaims_abandoned_processing_artifact(
    monkeypatch, migrated_database_url, migrated_session_factory
) -> None:
    old_started_at = datetime.now(UTC) - timedelta(hours=1)
    processed: list[UUID] = []

    async def _provision() -> UUID:
        async with migrated_session_factory() as session:
            async with session.begin():
                user = User(
                    external_auth_id=f"kc|{uuid4()}",
                    email="export-recovery@example.com",
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
                    status=ExportArtifactStatus.PROCESSING.value,
                    format=ExportArtifactFormat.JSON_ZIP.value,
                    storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                    schema_version="1.0",
                    queued_at=datetime.now(UTC) - timedelta(hours=1),
                    started_at=old_started_at,
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
                session.add(artifact)
                await session.flush()
                return artifact.id

    async def _process_artifact(*, artifact_id: UUID) -> None:
        processed.append(artifact_id)

    artifact_id = run_async(_provision())

    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.commands.privacy_export_worker._process_artifact",
        _process_artifact,
    )

    try:
        exit_code = run_async(run_worker(batch_size=1, dry_run=False, once=True))
    finally:
        get_settings.cache_clear()

    assert exit_code == 0
    assert processed == [artifact_id]

    async def _load_status():
        async with migrated_session_factory() as session:
            row = (
                await session.execute(
                    select(ExportArtifact).where(ExportArtifact.id == artifact_id)
                )
            ).scalar_one()
            return row.status, row.started_at

    status, started_at = run_async(_load_status())
    assert status == ExportArtifactStatus.PROCESSING.value
    assert started_at is not None
    assert started_at.replace(tzinfo=UTC) > old_started_at


def test_worker_does_not_reclaim_recent_processing_artifact(
    monkeypatch, migrated_database_url, migrated_session_factory
) -> None:
    processed: list[UUID] = []

    async def _provision() -> UUID:
        async with migrated_session_factory() as session:
            async with session.begin():
                user = User(
                    external_auth_id=f"kc|{uuid4()}",
                    email="export-recent-processing@example.com",
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
                    status=ExportArtifactStatus.PROCESSING.value,
                    format=ExportArtifactFormat.JSON_ZIP.value,
                    storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                    schema_version="1.0",
                    queued_at=datetime.now(UTC),
                    started_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
                session.add(artifact)
                await session.flush()
                return artifact.id

    async def _process_artifact(*, artifact_id: UUID) -> None:
        processed.append(artifact_id)

    artifact_id = run_async(_provision())

    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.commands.privacy_export_worker._process_artifact",
        _process_artifact,
    )

    try:
        exit_code = run_async(run_worker(batch_size=1, dry_run=False, once=True))
    finally:
        get_settings.cache_clear()

    assert exit_code == 0
    assert processed == []

    async def _load_status():
        async with migrated_session_factory() as session:
            row = (
                await session.execute(
                    select(ExportArtifact).where(ExportArtifact.id == artifact_id)
                )
            ).scalar_one()
            return row.status

    assert run_async(_load_status()) == ExportArtifactStatus.PROCESSING.value
