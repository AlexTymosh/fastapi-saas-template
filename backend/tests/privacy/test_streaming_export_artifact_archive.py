from __future__ import annotations

import json
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
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
from app.privacy.services import export_artifacts as export_artifacts_module
from app.privacy.services.export_artifacts import ExportArtifactService
from app.privacy.storage.base import StorageObjectState
from app.privacy.storage.s3 import S3CompatibleStorageAdapter
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async
from tests.helpers.privacy_exports import (
    generate_export_artifact_in_committed_phases,
)

pytestmark = [pytest.mark.privacy]


@pytest.fixture(autouse=True)
def isolated_export_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    storage_path = tmp_path / "privacy-exports"
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        yield storage_path
    finally:
        get_settings.cache_clear()


async def _create_user_and_dsr(session):
    now = datetime.now(UTC)
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
        submitted_at=now,
        due_at=now,
    )
    session.add(dsr)
    await session.flush()
    return user, dsr


async def _fake_streaming_export_chunks(*_args: object) -> AsyncIterator[str]:
    chunks = (
        '{"schema_version":"1.0",',
        '"data_subject_request_id":"streamed",',
        '"data":{},',
        '"manifest":{"record_count":0}}',
    )
    for chunk in chunks:
        yield chunk


def _read_export_payload(archive_bytes: bytes) -> dict[str, object]:
    with zipfile.ZipFile(BytesIO(archive_bytes), mode="r") as archive:
        assert archive.namelist() == ["export.json"]
        return json.loads(archive.read("export.json"))


def test_generate_export_artifact_uses_streaming_json_chunks(
    monkeypatch: pytest.MonkeyPatch,
    migrated_session_factory,
) -> None:
    monkeypatch.setattr(
        export_artifacts_module,
        "iter_subject_export_json_chunks",
        _fake_streaming_export_chunks,
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(session)
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            ready = await generate_export_artifact_in_committed_phases(
                session,
                artifact=artifact,
                generated_by_user_id=user.id,
            )

            assert ready.storage_key is not None
            assert ready.size_bytes is not None and ready.size_bytes > 0
            assert ready.checksum_sha256 is not None
            archive_bytes = service.storage.get_bytes(ready.storage_key)
            payload = _read_export_payload(archive_bytes)
            assert payload["data_subject_request_id"] == "streamed"
            assert payload["manifest"] == {"record_count": 0}

    run_async(_run())


def test_prepared_export_archive_uses_temporary_file_then_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    migrated_session_factory,
) -> None:
    monkeypatch.setattr(
        export_artifacts_module,
        "iter_subject_export_json_chunks",
        _fake_streaming_export_chunks,
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(session)
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            leases = await service.claim_queued_artifact_leases(batch_size=1)
            assert len(leases) == 1
            token = leases[0].processing_token
            await session.commit()

            prepared = await service.prepare_export_archive(
                artifact_id=artifact.id,
                processing_token=token,
            )
            await session.commit()
            assert prepared.archive_path.exists()
            assert prepared.size_bytes == prepared.archive_path.stat().st_size
            persisted = await service.repo.get_by_id(artifact.id)
            assert persisted is not None
            assert persisted.storage_key == prepared.storage_key
            assert persisted.filename == prepared.filename
            assert persisted.content_type == prepared.content_type
            assert persisted.size_bytes == prepared.size_bytes
            assert persisted.checksum_sha256 == prepared.checksum_sha256
            await session.commit()

            reservation = service.reserve_prepared_export_archive(
                prepared,
                processing_token=token,
            )
            try:
                await service.validate_prepared_export_upload(
                    prepared=prepared,
                    processing_token=token,
                )
                await session.commit()
                service.publish_prepared_export_archive(prepared, reservation)
            finally:
                service.cancel_prepared_export_archive_reservation(
                    prepared,
                    reservation,
                )
                service.discard_prepared_export_archive(prepared)

            assert not prepared.archive_path.exists()
            assert service.storage.exists(prepared.storage_key)

    run_async(_run())


def test_stale_retry_reuses_committed_upload_intent(
    migrated_session_factory,
    isolated_export_storage: Path,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(session)
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            artifact_id = artifact.id
            user_id = user.id
            first_lease = (await service.claim_queued_artifact_leases(batch_size=1))[0]
            await session.commit()

            first_prepared = await service.prepare_export_archive(
                artifact_id=artifact_id,
                processing_token=first_lease.processing_token,
            )
            assert first_prepared.archive_path is not None
            first_storage_key = first_prepared.storage_key
            first_checksum = first_prepared.checksum_sha256
            await session.commit()
            reservation = service.reserve_prepared_export_archive(
                first_prepared,
                processing_token=first_lease.processing_token,
            )
            try:
                await service.validate_prepared_export_upload(
                    prepared=first_prepared,
                    processing_token=first_lease.processing_token,
                )
                await session.commit()
                service.publish_prepared_export_archive(
                    first_prepared,
                    reservation,
                )
            finally:
                service.cancel_prepared_export_archive_reservation(
                    first_prepared,
                    reservation,
                )
                service.discard_prepared_export_archive(first_prepared)
            assert service.storage.exists(first_storage_key)

            processing = await service.repo.get_by_id(artifact_id)
            assert processing is not None
            processing.processing_lease_expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
            await service.repo.save(processing)
            await session.commit()

            second_lease = (await service.claim_queued_artifact_leases(batch_size=1))[0]
            assert second_lease.processing_token != first_lease.processing_token
            await session.commit()

            with pytest.raises(ConflictError, match="no longer active"):
                await service.validate_prepared_export_upload(
                    prepared=first_prepared,
                    processing_token=first_lease.processing_token,
                )
            await session.rollback()

            second_prepared = await service.prepare_export_archive(
                artifact_id=artifact_id,
                processing_token=second_lease.processing_token,
            )
            assert second_prepared.storage_key == first_storage_key
            assert second_prepared.checksum_sha256 == first_checksum
            assert second_prepared.archive_path is None
            await session.commit()
            await service.validate_prepared_export_upload(
                prepared=second_prepared,
                processing_token=second_lease.processing_token,
            )
            await session.commit()
            assert (
                service.inspect_committed_export_archive(second_prepared)
                == StorageObjectState.MATCHING
            )
            ready = await service.mark_generated_export_artifact_ready(
                artifact_id=artifact_id,
                prepared=second_prepared,
                generated_by_user_id=user_id,
                processing_token=second_lease.processing_token,
            )
            await session.commit()

            assert ready.status == ExportArtifactStatus.READY.value
            assert ready.storage_key == first_storage_key
            assert len(list(isolated_export_storage.rglob("*.zip"))) == 1

    run_async(_run())


def test_rejected_oversized_streaming_archive_removes_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    migrated_session_factory,
    isolated_export_storage: Path,
) -> None:
    monkeypatch.setenv("PRIVACY_EXPORTS__MAX_ARTIFACT_SIZE_BYTES", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(
        export_artifacts_module,
        "iter_subject_export_json_chunks",
        _fake_streaming_export_chunks,
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(session)
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            failed = await generate_export_artifact_in_committed_phases(
                session,
                artifact=artifact,
                generated_by_user_id=user.id,
            )

            assert failed.status == ExportArtifactStatus.FAILED.value
            assert failed.failure_reason_code == "artifact_too_large"
            assert not list(isolated_export_storage.glob("privacy-export-*.tmp"))

    run_async(_run())


class _FakeS3Client:
    def __init__(self) -> None:
        self.uploaded_body: bytes | None = None
        self.bucket_name: str | None = None
        self.object_key: str | None = None
        self.extra_args: dict[str, object] | None = None

    def upload_fileobj(
        self,
        fileobj,
        bucket_name: str,
        object_key: str,
        *,
        ExtraArgs: dict[str, object],
    ) -> None:
        self.uploaded_body = fileobj.read()
        self.bucket_name = bucket_name
        self.object_key = object_key
        self.extra_args = ExtraArgs


def test_s3_storage_adapter_streams_file_upload(tmp_path: Path) -> None:
    archive_path = tmp_path / "privacy-export.zip"
    archive_path.write_bytes(b"streamed archive payload")
    fake_client = _FakeS3Client()
    adapter = S3CompatibleStorageAdapter.__new__(S3CompatibleStorageAdapter)
    adapter.bucket_name = "privacy-export-test-bucket"
    adapter.key_prefix = "privacy-exports"
    adapter.server_side_encryption = "AES256"
    adapter.sse_kms_key_id = None
    adapter.client = fake_client

    stored = adapter.put_file(
        "exports/artifact-id/archive.zip",
        archive_path,
        "application/zip",
    )

    assert stored.key == "exports/artifact-id/archive.zip"
    assert stored.content_type == "application/zip"
    assert stored.size_bytes == archive_path.stat().st_size
    assert fake_client.uploaded_body == b"streamed archive payload"
    assert fake_client.bucket_name == "privacy-export-test-bucket"
    assert fake_client.object_key == "privacy-exports/exports/artifact-id/archive.zip"
    assert fake_client.extra_args == {
        "ContentType": "application/zip",
        "Metadata": {"privacy-artifact": "true"},
        "ServerSideEncryption": "AES256",
    }
