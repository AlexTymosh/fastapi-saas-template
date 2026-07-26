from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.audit.models.audit_event import AuditAction
from app.commands import privacy_export_worker as worker_module
from app.commands.privacy_export_worker import run_worker
from app.core.config.settings import get_settings
from app.privacy.models.data_subject_request import DataSubjectRequest
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.services.export_artifacts import (
    ExportArtifactService,
    PreparedExportArchive,
)
from app.privacy.storage.base import StorageObjectConflictError
from app.privacy.storage.local import LocalStorageAdapter
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


async def _provision_queued_artifact(session_factory) -> UUID:
    async with session_factory() as session:
        async with session.begin():
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"export-worker-{uuid4()}@example.com",
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
                status=ExportArtifactStatus.QUEUED.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                schema_version="1.0",
                queued_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            session.add(artifact)
            await session.flush()
            return artifact.id


def _configure_worker(
    monkeypatch: pytest.MonkeyPatch,
    *,
    database_url: str,
    storage_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE__URL", database_url)
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()


def _fail_generated_audit_event(monkeypatch: pytest.MonkeyPatch) -> None:
    original = ExportArtifactService._record_event

    async def _record_event(self, audit_context, action, artifact) -> None:
        if action == AuditAction.EXPORT_ARTIFACT_GENERATED:
            raise RuntimeError("ready audit persistence failed")
        await original(self, audit_context, action, artifact)

    monkeypatch.setattr(ExportArtifactService, "_record_event", _record_event)


def test_worker_once_dry_run_executes(monkeypatch, migrated_database_url) -> None:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    exit_code = run_async(run_worker(batch_size=1, dry_run=True, once=True))
    assert exit_code == 0


def test_worker_dry_run_without_once_exits_after_one_iteration(monkeypatch) -> None:
    calls: list[int] = []

    async def _count_queued_artifacts(*, batch_size: int) -> int:
        calls.append(batch_size)
        return 1

    monkeypatch.setattr(
        "app.commands.privacy_export_worker._count_queued_artifacts",
        _count_queued_artifacts,
    )

    exit_code = run_async(run_worker(batch_size=5, dry_run=True, once=False))

    assert exit_code == 0
    assert calls == [5]


def test_worker_stops_after_empty_iteration(monkeypatch) -> None:
    calls: list[int] = []
    processed: list[object] = []
    lease = object()
    batches = [[lease], []]

    async def _claim_queued_artifact_leases(*, batch_size: int):
        calls.append(batch_size)
        return batches.pop(0)

    async def _process_artifact(*, lease) -> None:
        processed.append(lease)

    monkeypatch.setattr(
        "app.commands.privacy_export_worker._claim_queued_artifact_leases",
        _claim_queued_artifact_leases,
    )
    monkeypatch.setattr(
        "app.commands.privacy_export_worker._process_artifact",
        _process_artifact,
    )

    exit_code = run_async(run_worker(batch_size=7, dry_run=False, once=False))

    assert exit_code == 0
    assert calls == [7, 7]
    assert processed == [lease]


def test_worker_dry_run_does_not_mutate_queued_artifact(
    monkeypatch, migrated_database_url, migrated_session_factory
) -> None:
    artifact_id = run_async(_provision_queued_artifact(migrated_session_factory))

    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    exit_code = run_async(run_worker(batch_size=1, dry_run=True, once=True))
    assert exit_code == 0

    async def _load_status():
        async with migrated_session_factory() as session:
            row = (
                await session.execute(
                    select(ExportArtifact).where(ExportArtifact.id == artifact_id)
                )
            ).scalar_one()
            return row.status, row.started_at, row.processing_token

    status, started_at, processing_token = run_async(_load_status())
    assert status == ExportArtifactStatus.QUEUED.value
    assert started_at is None
    assert processing_token is None


def test_worker_commits_upload_intent_before_storage_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    storage_path = tmp_path / "worker-exports"
    _configure_worker(
        monkeypatch,
        database_url=migrated_database_url,
        storage_path=storage_path,
    )
    artifact_id = run_async(_provision_queued_artifact(migrated_session_factory))
    _fail_generated_audit_event(monkeypatch)

    database_path = make_url(migrated_database_url).database
    assert database_path is not None
    observed_rows: list[tuple[str, str]] = []
    original_put_file = LocalStorageAdapter.put_file_if_absent

    def _put_file(self, key, path, content_type, *, checksum_sha256):
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                (
                    "SELECT status, storage_key FROM export_artifacts "
                    "WHERE storage_key = ?"
                ),
                (key,),
            ).fetchone()
        assert row is not None
        observed_rows.append((row[0], row[1]))
        return original_put_file(
            self,
            key,
            path,
            content_type,
            checksum_sha256=checksum_sha256,
        )

    monkeypatch.setattr(LocalStorageAdapter, "put_file_if_absent", _put_file)

    exit_code = run_async(run_worker(batch_size=1, dry_run=False, once=True))

    assert exit_code == 0
    assert len(observed_rows) == 1
    assert observed_rows[0][0] == ExportArtifactStatus.PROCESSING.value

    async def _load_failed_artifact():
        async with migrated_session_factory() as session:
            return await session.get(ExportArtifact, artifact_id)

    failed = run_async(_load_failed_artifact())
    assert failed is not None
    assert failed.status == ExportArtifactStatus.FAILED.value
    assert failed.storage_key is None
    assert not list(storage_path.rglob("*.zip"))


def test_worker_fences_storage_write_after_lease_turnover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    storage_path = tmp_path / "worker-exports"
    _configure_worker(
        monkeypatch,
        database_url=migrated_database_url,
        storage_path=storage_path,
    )
    monkeypatch.setattr(
        worker_module,
        "get_session_factory",
        lambda: migrated_session_factory,
    )
    artifact_id = run_async(_provision_queued_artifact(migrated_session_factory))
    storage_key = f"exports/{artifact_id}/fenced.zip"
    stale_payload = b"stale worker archive"
    current_payload = b"current worker archive"
    stale_path = tmp_path / "stale-worker.tmp"
    current_path = tmp_path / "current-worker.tmp"
    stale_path.write_bytes(stale_payload)
    current_path.write_bytes(current_payload)
    stale_checksum = hashlib.sha256(stale_payload).hexdigest()
    current_checksum = hashlib.sha256(current_payload).hexdigest()
    stale_write_started = threading.Event()
    release_stale_write = threading.Event()
    original_put_file = LocalStorageAdapter.put_file_if_absent

    def _controlled_put_file(
        self,
        key,
        path,
        content_type,
        *,
        checksum_sha256,
    ):
        if path == stale_path:
            stale_write_started.set()
            if not release_stale_write.wait(timeout=10):
                raise TimeoutError("Timed out waiting to release stale write")
        return original_put_file(
            self,
            key,
            path,
            content_type,
            checksum_sha256=checksum_sha256,
        )

    monkeypatch.setattr(
        LocalStorageAdapter,
        "put_file_if_absent",
        _controlled_put_file,
    )

    async def _run() -> tuple[str, str | None]:
        async with migrated_session_factory() as session:
            async with session.begin():
                service = ExportArtifactService(session)
                stale_lease = (
                    await service.claim_queued_artifact_leases(batch_size=1)
                )[0]
                intent = await service.repo.ensure_processing_upload_intent(
                    artifact_id=artifact_id,
                    processing_token=stale_lease.processing_token,
                    candidate_storage_key=storage_key,
                    now=datetime.now(UTC),
                )
                assert intent is not None

        stale_prepared = PreparedExportArchive(
            artifact_id=artifact_id,
            storage_backend=ExportArtifactStorageBackend.LOCAL.value,
            storage_key=storage_key,
            filename="privacy-export.zip",
            content_type="application/zip",
            archive_path=stale_path,
            size_bytes=len(stale_payload),
            checksum_sha256=stale_checksum,
        )
        stale_write = asyncio.create_task(
            worker_module._write_export_archive(
                lease=stale_lease,
                prepared=stale_prepared,
            )
        )

        try:
            started = await asyncio.to_thread(stale_write_started.wait, 10)
            assert started

            async with migrated_session_factory() as session:
                async with session.begin():
                    service = ExportArtifactService(session)
                    artifact = await service.repo.get_by_id(artifact_id)
                    assert artifact is not None
                    artifact.processing_lease_expires_at = datetime.now(
                        UTC
                    ) - timedelta(seconds=1)
                    await service.repo.save(artifact)

            async with migrated_session_factory() as session:
                async with session.begin():
                    service = ExportArtifactService(session)
                    current_lease = (
                        await service.claim_queued_artifact_leases(batch_size=1)
                    )[0]

            current_prepared = PreparedExportArchive(
                artifact_id=artifact_id,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=storage_key,
                filename="privacy-export.zip",
                content_type="application/zip",
                archive_path=current_path,
                size_bytes=len(current_payload),
                checksum_sha256=current_checksum,
            )
            await worker_module._write_export_archive(
                lease=current_lease,
                prepared=current_prepared,
            )
            await worker_module._mark_export_ready(
                lease=current_lease,
                prepared=current_prepared,
            )
        finally:
            release_stale_write.set()

        with pytest.raises(StorageObjectConflictError):
            await stale_write

        async with migrated_session_factory() as session:
            artifact = await session.get(ExportArtifact, artifact_id)
            assert artifact is not None
            return artifact.status, artifact.checksum_sha256

    status, checksum = run_async(_run())

    storage = LocalStorageAdapter(str(storage_path), "test-secret")
    assert status == ExportArtifactStatus.READY.value
    assert checksum == current_checksum
    assert storage.get_bytes(storage_key) == current_payload


def test_worker_cleans_partial_object_when_upload_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    storage_path = tmp_path / "worker-exports"
    _configure_worker(
        monkeypatch,
        database_url=migrated_database_url,
        storage_path=storage_path,
    )
    artifact_id = run_async(_provision_queued_artifact(migrated_session_factory))
    original_put_file = LocalStorageAdapter.put_file_if_absent

    def _put_then_fail(self, key, path, content_type, *, checksum_sha256):
        original_put_file(
            self,
            key,
            path,
            content_type,
            checksum_sha256=checksum_sha256,
        )
        raise RuntimeError("upload acknowledgement failed")

    monkeypatch.setattr(
        LocalStorageAdapter,
        "put_file_if_absent",
        _put_then_fail,
    )

    exit_code = run_async(run_worker(batch_size=1, dry_run=False, once=True))

    assert exit_code == 0

    async def _load_failed_artifact():
        async with migrated_session_factory() as session:
            return await session.get(ExportArtifact, artifact_id)

    failed = run_async(_load_failed_artifact())
    assert failed is not None
    assert failed.status == ExportArtifactStatus.FAILED.value
    assert failed.storage_key is None
    assert not list(storage_path.rglob("*.zip"))


def test_worker_retains_failed_upload_key_when_immediate_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    storage_path = tmp_path / "worker-exports"
    _configure_worker(
        monkeypatch,
        database_url=migrated_database_url,
        storage_path=storage_path,
    )
    artifact_id = run_async(_provision_queued_artifact(migrated_session_factory))
    _fail_generated_audit_event(monkeypatch)
    original_delete = LocalStorageAdapter.delete

    def _fail_delete(self, key: str) -> None:
        raise RuntimeError("storage cleanup unavailable")

    monkeypatch.setattr(LocalStorageAdapter, "delete", _fail_delete)

    exit_code = run_async(run_worker(batch_size=1, dry_run=False, once=True))

    assert exit_code == 0

    async def _load_failed_artifact():
        async with migrated_session_factory() as session:
            return await session.get(ExportArtifact, artifact_id)

    failed = run_async(_load_failed_artifact())
    assert failed is not None
    assert failed.status == ExportArtifactStatus.FAILED.value
    assert failed.storage_key is not None
    assert list(storage_path.rglob("*.zip"))

    monkeypatch.setattr(LocalStorageAdapter, "delete", original_delete)

    async def _retry_cleanup() -> ExportArtifact:
        async with migrated_session_factory() as session:
            async with session.begin():
                processed = await ExportArtifactService(session).mark_expired_artifacts(
                    limit=1
                )
                assert processed == 1
            persisted = await session.get(ExportArtifact, artifact_id)
            assert persisted is not None
            return persisted

    cleaned = run_async(_retry_cleanup())
    assert cleaned.storage_key is None
    assert not list(storage_path.rglob("*.zip"))
