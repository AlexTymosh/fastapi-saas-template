from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.commands.privacy_export_worker import run_worker
from app.privacy.models.data_subject_request import DataSubjectRequest
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


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
    async def _provision() -> UUID:
        async with migrated_session_factory() as session:
            async with session.begin():
                user = User(
                    external_auth_id=f"kc|{uuid4()}",
                    email="export-worker@example.com",
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

    artifact_id = run_async(_provision())

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
