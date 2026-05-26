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
