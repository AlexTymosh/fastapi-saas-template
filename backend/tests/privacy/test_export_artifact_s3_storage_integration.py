from __future__ import annotations

import hashlib
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from testcontainers.core.container import DockerContainer

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import (
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.services.export_artifacts import ExportArtifactService
from app.privacy.storage.base import StorageObjectConflictError
from app.privacy.storage.s3 import S3CompatibleStorageAdapter
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [
    pytest.mark.privacy,
    pytest.mark.integration,
    pytest.mark.container,
    pytest.mark.slow,
]

_MINIO_ACCESS_KEY = "minioadmin"
_MINIO_SECRET_KEY = "minioadmin"
_MINIO_REGION = "us-east-1"
_MINIO_PORT = 9000
_MINIO_IMAGE = "minio/minio:latest"


@dataclass(frozen=True)
class MinioExportStorage:
    endpoint_url: str
    bucket_name: str
    key_prefix: str
    adapter: S3CompatibleStorageAdapter


def _new_storage_adapter(
    *,
    endpoint_url: str,
    bucket_name: str,
    key_prefix: str,
) -> S3CompatibleStorageAdapter:
    return S3CompatibleStorageAdapter(
        bucket_name=bucket_name,
        region_name=_MINIO_REGION,
        endpoint_url=endpoint_url,
        access_key_id=_MINIO_ACCESS_KEY,
        secret_access_key=_MINIO_SECRET_KEY,
        key_prefix=key_prefix,
        server_side_encryption=None,
        addressing_style="path",
        connect_timeout_seconds=1.0,
        read_timeout_seconds=5.0,
        max_attempts=2,
    )


def _create_bucket_when_ready(
    adapter: S3CompatibleStorageAdapter,
    *,
    bucket_name: str,
) -> None:
    deadline = time.monotonic() + 45.0
    retryable_errors = (
        ConnectionClosedError,
        ConnectTimeoutError,
        EndpointConnectionError,
        ReadTimeoutError,
    )

    while True:
        try:
            adapter.client.create_bucket(Bucket=bucket_name)
            return
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                return
            if time.monotonic() >= deadline:
                raise
        except retryable_errors:
            if time.monotonic() >= deadline:
                raise

        time.sleep(0.25)


def _delete_bucket_objects(adapter: S3CompatibleStorageAdapter) -> None:
    response = adapter.client.list_objects_v2(Bucket=adapter.bucket_name)
    objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
    if objects:
        adapter.client.delete_objects(
            Bucket=adapter.bucket_name,
            Delete={"Objects": objects},
        )


@pytest.fixture(scope="session")
def minio_endpoint_url() -> Iterator[str]:
    command = f"server /data --address :{_MINIO_PORT} --console-address :9001"
    with (
        DockerContainer(_MINIO_IMAGE)
        .with_env("MINIO_ROOT_USER", _MINIO_ACCESS_KEY)
        .with_env("MINIO_ROOT_PASSWORD", _MINIO_SECRET_KEY)
        .with_command(command)
        .with_exposed_ports(_MINIO_PORT)
    ) as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(_MINIO_PORT)
        yield f"http://{host}:{port}"


@pytest.fixture
def minio_export_storage(minio_endpoint_url: str) -> Iterator[MinioExportStorage]:
    bucket_name = f"privacy-exports-{uuid4().hex}"
    key_prefix = f"integration-tests/{uuid4().hex}"
    adapter = _new_storage_adapter(
        endpoint_url=minio_endpoint_url,
        bucket_name=bucket_name,
        key_prefix=key_prefix,
    )
    _create_bucket_when_ready(adapter, bucket_name=bucket_name)

    try:
        yield MinioExportStorage(
            endpoint_url=minio_endpoint_url,
            bucket_name=bucket_name,
            key_prefix=key_prefix,
            adapter=adapter,
        )
    finally:
        _delete_bucket_objects(adapter)
        adapter.client.delete_bucket(Bucket=bucket_name)


def _configure_s3_privacy_exports(
    monkeypatch: pytest.MonkeyPatch,
    storage: MinioExportStorage,
) -> None:
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv(
        "PRIVACY_EXPORTS__STORAGE_BACKEND",
        ExportArtifactStorageBackend.S3_COMPATIBLE.value,
    )
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_ENDPOINT_URL", storage.endpoint_url)
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_REGION_NAME", _MINIO_REGION)
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_BUCKET_NAME", storage.bucket_name)
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_ACCESS_KEY_ID", _MINIO_ACCESS_KEY)
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_SECRET_ACCESS_KEY", _MINIO_SECRET_KEY)
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_KEY_PREFIX", storage.key_prefix)
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_SERVER_SIDE_ENCRYPTION", "")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_ADDRESSING_STYLE", "path")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_CONNECT_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_READ_TIMEOUT_SECONDS", "5.0")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()


async def _create_user_and_dsr(session) -> tuple[User, DataSubjectRequest]:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
    )
    session.add(user)
    await session.flush()

    now = datetime.now(UTC)
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


def test_s3_compatible_storage_adapter_round_trips_with_minio(
    minio_export_storage: MinioExportStorage,
) -> None:
    adapter = minio_export_storage.adapter
    storage_key = f"exports/{uuid4()}/archive.zip"
    payload = b"minio privacy export payload"

    stored = adapter.put_bytes(storage_key, payload, "application/zip")

    assert stored.key == storage_key
    assert stored.content_type == "application/zip"
    assert stored.size_bytes == len(payload)
    assert adapter.exists(storage_key)
    assert adapter.get_bytes(storage_key) == payload

    download_url = adapter.generate_download_url(storage_key, expires_in_seconds=60)
    with urllib.request.urlopen(download_url, timeout=5) as response:
        assert response.status == 200
        assert response.read() == payload

    adapter.delete(storage_key)

    assert not adapter.exists(storage_key)

    adapter.delete(storage_key)


def test_s3_compatible_storage_conditional_publish_does_not_overwrite(
    minio_export_storage: MinioExportStorage,
    tmp_path,
) -> None:
    adapter = minio_export_storage.adapter
    storage_key = f"exports/{uuid4()}/archive.zip"
    first_path = tmp_path / "first.zip"
    first_payload = b"first minio privacy export"
    first_path.write_bytes(first_payload)
    first_checksum = hashlib.sha256(first_payload).hexdigest()

    reservation = adapter.reserve_file_publication(
        storage_key,
        owner_token="first-worker",
    )
    adapter.publish_reserved_file(
        reservation,
        first_path,
        "application/zip",
        checksum_sha256=first_checksum,
    )

    with pytest.raises(StorageObjectConflictError):
        adapter.reserve_file_publication(
            storage_key,
            owner_token="second-worker",
        )

    assert adapter.get_bytes(storage_key) == first_payload


def test_s3_compatible_cleanup_fences_reserved_publication(
    minio_export_storage: MinioExportStorage,
    tmp_path,
) -> None:
    adapter = minio_export_storage.adapter
    storage_key = f"exports/{uuid4()}/archive.zip"
    archive_path = tmp_path / "archive.zip"
    payload = b"late minio privacy export"
    archive_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    reservation = adapter.reserve_file_publication(
        storage_key,
        owner_token="stale-worker",
    )

    adapter.delete(storage_key)

    with pytest.raises(StorageObjectConflictError):
        adapter.publish_reserved_file(
            reservation,
            archive_path,
            "application/zip",
            checksum_sha256=checksum,
        )

    assert not adapter.exists(storage_key)


def test_export_artifact_retention_expires_before_purging_minio_object(
    migrated_session_factory,
    minio_export_storage: MinioExportStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_s3_privacy_exports(monkeypatch, minio_export_storage)

    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(session)
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            storage_key = f"exports/{artifact.id}/retention.zip"
            service.storage.put_bytes(
                storage_key,
                b"retention-payload",
                "application/zip",
            )

            expired_at = datetime.now(UTC) - timedelta(seconds=1)
            artifact.status = ExportArtifactStatus.READY.value
            artifact.storage_backend = ExportArtifactStorageBackend.S3_COMPATIBLE.value
            artifact.storage_key = storage_key
            artifact.filename = "retention.zip"
            artifact.content_type = "application/zip"
            artifact.size_bytes = 17
            artifact.checksum_sha256 = "0" * 64
            artifact.completed_at = expired_at - timedelta(minutes=1)
            artifact.expires_at = expired_at
            await service.repo.save(artifact)

            expired_count = await service.mark_expired_artifacts(now=datetime.now(UTC))
            expired = await service.repo.get_by_id(artifact.id)

            assert expired_count == 1
            assert expired is not None
            assert expired.status == ExportArtifactStatus.EXPIRED.value
            assert expired.storage_key == storage_key
            assert expired.filename == "retention.zip"
            assert expired.content_type == "application/zip"
            assert expired.size_bytes == 17
            assert expired.checksum_sha256 == "0" * 64
            assert minio_export_storage.adapter.exists(storage_key)

            await session.commit()
            service = ExportArtifactService(session)

            purged_count = await service.mark_expired_artifacts(now=datetime.now(UTC))
            purged = await service.repo.get_by_id(artifact.id)

            assert purged_count == 1
            assert purged is not None
            assert purged.status == ExportArtifactStatus.EXPIRED.value
            assert purged.storage_key is None
            assert purged.filename is None
            assert purged.content_type is None
            assert purged.size_bytes is None
            assert purged.checksum_sha256 is None
            assert not minio_export_storage.adapter.exists(storage_key)

    try:
        run_async(_run())
    finally:
        get_settings.cache_clear()
