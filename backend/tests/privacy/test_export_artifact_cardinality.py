from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import ExportArtifactStatus
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


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


def test_export_dsr_records_multi_artifact_history(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_approved_export_dsr(session)
            service = ExportArtifactService(session)

            first_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            second_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            artifacts = await service.repo.get_by_dsr_id(dsr.id)
            artifact_ids = {artifact.id for artifact in artifacts}
            persisted = await service.dsr_repo.get_by_id(dsr.id)

            assert artifact_ids == {first_artifact.id, second_artifact.id}
            assert all(
                artifact.data_subject_request_id == dsr.id for artifact in artifacts
            )
            assert persisted is not None
            assert persisted.export_artifact_id is None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )

    run_async(_run())


def test_newer_queued_artifact_is_current_execution_source(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_approved_export_dsr(session)
            service = ExportArtifactService(session)

            old_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            old_artifact.status = ExportArtifactStatus.READY.value
            old_artifact.storage_key = f"exports/{old_artifact.id}/artifact.zip"
            old_artifact.completed_at = datetime.now(UTC) - timedelta(minutes=2)
            old_artifact.expires_at = datetime.now(UTC) + timedelta(seconds=60)
            service.storage.put_bytes(
                old_artifact.storage_key,
                b"payload",
                "application/zip",
            )
            await service.repo.save(old_artifact)

            dsr.execution_status = DataSubjectRequestExecutionStatus.DELIVERED.value
            dsr.execution_completed_at = old_artifact.completed_at
            await service.dsr_repo.save(dsr)

            await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            download = await service.generate_download_url(
                artifact=old_artifact,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            assert 0 < download.expires_in_seconds <= 60
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert persisted.export_artifact_id is None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())
