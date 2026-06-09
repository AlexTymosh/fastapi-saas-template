from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.privacy.maintenance import expire_ready_export_artifacts
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import ExportArtifactStatus
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


@pytest.fixture(autouse=True)
def isolated_export_storage(monkeypatch, tmp_path):
    storage_path = tmp_path / "privacy-exports"
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        yield storage_path
    finally:
        get_settings.cache_clear()


async def _create_approved_export_dsr(session):
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    dsr = DataSubjectRequest(
        request_type="export",
        status=DataSubjectRequestStatus.APPROVED.value,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=datetime.now(UTC),
        due_at=datetime.now(UTC),
    )
    session.add(dsr)
    await session.flush()
    return user, dsr


async def _create_expired_ready_artifact(session):
    user, dsr = await _create_approved_export_dsr(session)
    service = ExportArtifactService(session)
    artifact = await service.request_export_artifact(
        request_id=dsr.id,
        requested_by_user_id=user.id,
        audit_context=AuditContext(actor_user_id=user.id),
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    storage_key = f"exports/{artifact.id}/artifact.zip"
    artifact.status = ExportArtifactStatus.READY.value
    artifact.storage_key = storage_key
    artifact.filename = "artifact.zip"
    artifact.content_type = "application/zip"
    artifact.size_bytes = 7
    artifact.checksum_sha256 = "0" * 64
    artifact.completed_at = expired_at - timedelta(minutes=1)
    artifact.expires_at = expired_at
    await service.repo.save(artifact)
    service.storage.put_bytes(storage_key, b"payload", "application/zip")
    dsr.execution_status = DataSubjectRequestExecutionStatus.READY.value
    dsr.execution_completed_at = artifact.completed_at
    await service.dsr_repo.save(dsr)
    return artifact.id, storage_key, dsr.id


def test_privacy_retention_dry_run_does_not_mutate_or_delete_storage(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            artifact_id, storage_key, dsr_id = await _create_expired_ready_artifact(
                session
            )
            service = ExportArtifactService(session)

            count = await expire_ready_export_artifacts(session, dry_run=True)

            assert count == 1
            persisted_artifact = await service.repo.get_by_id(artifact_id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.READY.value
            assert persisted_artifact.storage_key == storage_key
            assert service.storage.exists(storage_key) is True
            persisted_dsr = await service.dsr_repo.get_by_id(dsr_id)
            assert persisted_dsr is not None
            assert (
                persisted_dsr.execution_status
                == DataSubjectRequestExecutionStatus.READY.value
            )

    run_async(_run())


def test_privacy_retention_expires_and_purges_storage_object(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            artifact_id, storage_key, dsr_id = await _create_expired_ready_artifact(
                session
            )
            service = ExportArtifactService(session)

            count = await expire_ready_export_artifacts(session)

            assert count == 1
            persisted_artifact = await service.repo.get_by_id(artifact_id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.EXPIRED.value
            assert persisted_artifact.storage_key is None
            assert persisted_artifact.filename is None
            assert persisted_artifact.content_type is None
            assert persisted_artifact.size_bytes is None
            assert persisted_artifact.checksum_sha256 is None
            assert service.storage.exists(storage_key) is False
            persisted_dsr = await service.dsr_repo.get_by_id(dsr_id)
            assert persisted_dsr is not None
            assert (
                persisted_dsr.execution_status
                == DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert persisted_dsr.execution_failure_reason_code == "artifact_expired"

    run_async(_run())
