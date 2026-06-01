from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.core.errors import ConflictError
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import (
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
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


async def _create_user_and_dsr(session, *, request_type: str, status: str):
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    dsr = DataSubjectRequest(
        request_type=request_type,
        status=status,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=datetime.now(UTC),
        due_at=datetime.now(UTC),
    )
    session.add(dsr)
    await session.flush()
    return user, dsr


def _read_export_payload(archive_bytes: bytes) -> dict[str, object]:
    with zipfile.ZipFile(BytesIO(archive_bytes), mode="r") as archive:
        assert archive.namelist() == ["export.json"]
        return json.loads(archive.read("export.json"))


def test_request_rejects_disabled_export_feature(
    monkeypatch, migrated_session_factory
) -> None:
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "false")
    get_settings.cache_clear()

    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            with pytest.raises(ConflictError, match="disabled"):
                await service.request_export_artifact(
                    request_id=dsr.id,
                    requested_by_user_id=user.id,
                    audit_context=AuditContext(actor_user_id=user.id),
                )

    run_async(_run())


def test_request_requires_approved_export_dsr(migrated_session_factory):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="erase",
                status=DataSubjectRequestStatus.SUBMITTED.value,
            )
            service = ExportArtifactService(session)
            with pytest.raises(ConflictError):
                await service.request_export_artifact(
                    request_id=dsr.id,
                    requested_by_user_id=user.id,
                    audit_context=AuditContext(actor_user_id=user.id),
                )

    run_async(_run())


def test_request_export_artifact_marks_dsr_execution_queued(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)

            await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )
            assert persisted.execution_started_at is None
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is None

    run_async(_run())


def test_request_export_artifact_clears_stale_completion_when_requeued(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            stale_time = datetime.now(UTC) - timedelta(days=1)
            dsr.execution_status = DataSubjectRequestExecutionStatus.DELIVERED.value
            dsr.execution_started_at = stale_time
            dsr.execution_completed_at = stale_time
            dsr.execution_failed_at = stale_time
            dsr.execution_failure_reason_code = "old_failure"
            dsr.execution_failure_detail = "Old failure detail"
            service = ExportArtifactService(session)

            await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )
            assert persisted.execution_started_at is None
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())


def test_claim_queued_artifact_marks_dsr_execution_processing(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            leases = await service.claim_queued_artifact_leases(batch_size=1)

            assert len(leases) == 1
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.PROCESSING.value
            )
            assert persisted.execution_started_at is not None

    run_async(_run())


@pytest.mark.parametrize(
    "completed_status",
    [
        DataSubjectRequestExecutionStatus.READY,
        DataSubjectRequestExecutionStatus.DELIVERED,
    ],
)
def test_recover_stale_processing_preserves_completed_dsr_execution_state(
    migrated_session_factory,
    completed_status: DataSubjectRequestExecutionStatus,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            stale_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            leases = await service.claim_queued_artifact_leases(batch_size=1)
            assert len(leases) == 1

            stale_artifact = await service.repo.get_by_id(stale_artifact.id)
            assert stale_artifact is not None
            stale_started_at = datetime.now(UTC) - timedelta(minutes=10)
            stale_artifact.queued_at = stale_started_at - timedelta(minutes=1)
            stale_artifact.started_at = stale_started_at
            stale_artifact.processing_lease_expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
            await service.repo.save(stale_artifact)

            completed_at = datetime.now(UTC)
            await service.repo.create(
                data_subject_request_id=dsr.id,
                subject_user_id=dsr.subject_user_id,
                requester_user_id=dsr.requester_user_id,
                status=ExportArtifactStatus.READY.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                schema_version="1.0",
                requested_by_user_id=user.id,
                generated_by_user_id=user.id,
                storage_key=f"exports/{uuid4()}/artifact.zip",
                filename="artifact.zip",
                content_type="application/zip",
                size_bytes=1,
                checksum_sha256="0" * 64,
                queued_at=completed_at - timedelta(minutes=2),
                started_at=completed_at - timedelta(minutes=1),
                completed_at=completed_at,
                expires_at=completed_at + timedelta(days=1),
                downloaded_at=(
                    completed_at
                    if completed_status is DataSubjectRequestExecutionStatus.DELIVERED
                    else None
                ),
                download_count=(
                    1
                    if completed_status is DataSubjectRequestExecutionStatus.DELIVERED
                    else 0
                ),
            )
            dsr.execution_status = completed_status.value
            dsr.execution_started_at = completed_at - timedelta(minutes=4)
            dsr.execution_completed_at = completed_at
            await service.dsr_repo.save(dsr)

            recovered = await service.recover_stale_processing_artifacts(limit=10)

            assert recovered == 1
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert persisted.execution_status == completed_status.value
            assert persisted.execution_completed_at is not None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())


def test_recover_stale_processing_respects_newer_export_run(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            old_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            downloaded_at = datetime.now(UTC) - timedelta(minutes=5)
            old_artifact.status = ExportArtifactStatus.READY.value
            old_artifact.storage_key = f"exports/{old_artifact.id}/artifact.zip"
            old_artifact.completed_at = downloaded_at - timedelta(minutes=1)
            old_artifact.expires_at = datetime.now(UTC) + timedelta(days=1)
            old_artifact.downloaded_at = downloaded_at
            old_artifact.download_count = 1
            await service.repo.save(old_artifact)
            dsr.execution_status = DataSubjectRequestExecutionStatus.DELIVERED.value
            dsr.execution_completed_at = old_artifact.completed_at
            await service.dsr_repo.save(dsr)

            new_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            leases = await service.claim_queued_artifact_leases(batch_size=1)
            assert len(leases) == 1
            new_artifact = await service.repo.get_by_id(new_artifact.id)
            assert new_artifact is not None
            new_artifact.processing_lease_expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
            await service.repo.save(new_artifact)

            recovered = await service.recover_stale_processing_artifacts(limit=10)

            assert recovered == 1
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())


def test_old_ready_download_does_not_overwrite_newer_queued_run(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
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
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())


def test_old_processing_completion_does_not_overwrite_newer_queued_run(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            old_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            leases = await service.claim_queued_artifact_leases(batch_size=1)
            assert len(leases) == 1

            await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            old_artifact = await service.repo.get_by_id(old_artifact.id)
            assert old_artifact is not None

            ready = await service.generate_export_artifact(
                artifact=old_artifact,
                generated_by_user_id=user.id,
                processing_token=leases[0].processing_token,
            )

            assert ready.status == ExportArtifactStatus.READY.value
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())


def test_generate_export_artifact_marks_ready(migrated_session_factory):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            artifact.status = ExportArtifactStatus.PROCESSING.value
            ready = await service.generate_export_artifact(
                artifact=artifact, generated_by_user_id=user.id
            )
            assert ready.status == ExportArtifactStatus.READY.value
            assert ready.storage_key is not None
            assert ready.filename is not None
            assert ready.content_type == "application/zip"
            assert ready.size_bytes is not None and ready.size_bytes > 0
            assert ready.checksum_sha256 is not None
            assert service.storage.exists(ready.storage_key)

            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.READY.value
            )
            assert persisted.execution_started_at is not None
            assert persisted.execution_completed_at is not None
            assert persisted.execution_failed_at is None

    run_async(_run())


def test_generate_export_artifact_zip_contains_minimal_schema(migrated_session_factory):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            artifact.status = ExportArtifactStatus.PROCESSING.value
            ready = await service.generate_export_artifact(
                artifact=artifact, generated_by_user_id=user.id
            )

            assert ready.storage_key is not None
            payload = _read_export_payload(service.storage.get_bytes(ready.storage_key))
            assert payload["schema_version"] == "1.0"
            assert payload["data_subject_request_id"] == str(dsr.id)
            assert payload["subject_user_id"] == str(user.id)
            assert payload["requester_user_id"] == str(user.id)
            assert payload["request_type"] == "export"
            assert payload["request_status"] == DataSubjectRequestStatus.APPROVED.value
            assert payload["artifact_id"] == str(ready.id)
            assert "generated_at" in payload

    run_async(_run())


def test_generate_export_artifact_too_large_marks_failed(
    monkeypatch, migrated_session_factory
):
    monkeypatch.setenv("PRIVACY_EXPORTS__MAX_ARTIFACT_SIZE_BYTES", "1")
    get_settings.cache_clear()

    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            artifact.status = ExportArtifactStatus.PROCESSING.value
            failed = await service.generate_export_artifact(
                artifact=artifact, generated_by_user_id=user.id
            )

            assert failed.status == ExportArtifactStatus.FAILED.value
            assert failed.failure_reason_code == "artifact_too_large"
            assert failed.storage_key is None

            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert persisted.execution_failed_at is not None
            assert persisted.execution_failure_reason_code == "artifact_too_large"
            assert persisted.execution_failure_detail == "Export generation failed"

    run_async(_run())


def test_generate_export_artifact_fails_when_dsr_no_longer_eligible(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            artifact.status = ExportArtifactStatus.PROCESSING.value
            dsr.status = DataSubjectRequestStatus.CANCELLED.value

            failed = await service.generate_export_artifact(
                artifact=artifact, generated_by_user_id=user.id
            )

            assert failed.status == ExportArtifactStatus.FAILED.value
            assert failed.failure_reason_code == "dsr_not_export_eligible"
            assert failed.storage_key is None

    run_async(_run())


def test_mark_expired_artifacts_marks_dsr_failed_when_only_ready_artifact_expires(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            expired_at = datetime.now(UTC) - timedelta(seconds=1)
            artifact.status = ExportArtifactStatus.READY.value
            artifact.storage_key = f"exports/{artifact.id}/artifact.zip"
            artifact.completed_at = expired_at - timedelta(minutes=1)
            artifact.expires_at = expired_at
            await service.repo.save(artifact)
            dsr.execution_status = DataSubjectRequestExecutionStatus.READY.value
            dsr.execution_completed_at = artifact.completed_at
            await service.dsr_repo.save(dsr)

            expired = await service.mark_expired_artifacts(now=datetime.now(UTC))

            assert expired == 1
            persisted_artifact = await service.repo.get_by_id(artifact.id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.EXPIRED.value
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is not None
            assert persisted.execution_failure_reason_code == "artifact_expired"
            assert (
                persisted.execution_failure_detail
                == "Export artifact expired before delivery"
            )

    run_async(_run())


def test_mark_expired_artifacts_preserves_delivered_dsr_execution_state(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            downloaded_at = datetime.now(UTC) - timedelta(minutes=1)
            artifact.status = ExportArtifactStatus.READY.value
            artifact.storage_key = f"exports/{artifact.id}/artifact.zip"
            artifact.completed_at = downloaded_at - timedelta(minutes=1)
            artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            artifact.downloaded_at = downloaded_at
            artifact.download_count = 1
            await service.repo.save(artifact)
            dsr.execution_status = DataSubjectRequestExecutionStatus.DELIVERED.value
            dsr.execution_completed_at = artifact.completed_at
            await service.dsr_repo.save(dsr)

            expired = await service.mark_expired_artifacts(now=datetime.now(UTC))

            assert expired == 1
            persisted_artifact = await service.repo.get_by_id(artifact.id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.EXPIRED.value
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.DELIVERED.value
            )
            assert persisted.execution_completed_at is not None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())


def test_mark_expired_artifacts_respects_newer_queued_export_run(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            old_artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            downloaded_at = datetime.now(UTC) - timedelta(minutes=5)
            old_artifact.status = ExportArtifactStatus.READY.value
            old_artifact.storage_key = f"exports/{old_artifact.id}/artifact.zip"
            old_artifact.completed_at = downloaded_at - timedelta(minutes=1)
            old_artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            old_artifact.downloaded_at = downloaded_at
            old_artifact.download_count = 1
            await service.repo.save(old_artifact)
            dsr.execution_status = DataSubjectRequestExecutionStatus.DELIVERED.value
            dsr.execution_completed_at = old_artifact.completed_at
            await service.dsr_repo.save(dsr)

            await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            expired = await service.mark_expired_artifacts(now=datetime.now(UTC))

            assert expired == 1
            persisted_old_artifact = await service.repo.get_by_id(old_artifact.id)
            assert persisted_old_artifact is not None
            assert persisted_old_artifact.status == ExportArtifactStatus.EXPIRED.value
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.QUEUED.value
            )
            assert persisted.execution_completed_at is None
            assert persisted.execution_failed_at is None
            assert persisted.execution_failure_reason_code is None
            assert persisted.execution_failure_detail is None

    run_async(_run())


def test_generate_download_url_marks_dsr_execution_delivered(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            artifact.status = ExportArtifactStatus.READY.value
            artifact.storage_key = f"exports/{artifact.id}/artifact.zip"
            artifact.expires_at = datetime.now(UTC) + timedelta(seconds=60)
            service.storage.put_bytes(
                artifact.storage_key,
                b"payload",
                "application/zip",
            )

            download = await service.generate_download_url(
                artifact=artifact,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            assert 0 < download.expires_in_seconds <= 60
            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.DELIVERED.value
            )
            assert persisted.execution_completed_at is not None

    run_async(_run())


def test_generate_download_url_clamps_ttl_to_artifact_remaining_lifetime(
    migrated_session_factory,
):
    async def _run():
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            artifact.status = ExportArtifactStatus.READY.value
            artifact.storage_key = f"exports/{artifact.id}/artifact.zip"
            artifact.expires_at = datetime.now(UTC) + timedelta(seconds=60)
            service.storage.put_bytes(
                artifact.storage_key,
                b"payload",
                "application/zip",
            )

            download = await service.generate_download_url(
                artifact=artifact,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            assert 0 < download.expires_in_seconds <= 60
            assert service.storage.verify_download_url(
                download.url,
                expected_key=artifact.storage_key,
            )

    run_async(_run())
