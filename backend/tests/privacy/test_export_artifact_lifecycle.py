from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.privacy.export_artifact_lifecycle import (
    SUBJECT_ERASURE_CANCELLED_EXPORT_REASON,
    cancel_export_artifact_for_subject_erasure,
    clear_export_artifact_storage_metadata,
    mark_export_artifact_expired,
    mark_export_artifact_failed,
    mark_export_artifact_ready,
)
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)

pytestmark = [pytest.mark.privacy]


def _artifact(*, status: ExportArtifactStatus) -> ExportArtifact:
    now = datetime.now(UTC)
    return ExportArtifact(
        data_subject_request_id=uuid4(),
        subject_user_id=uuid4(),
        requester_user_id=uuid4(),
        status=status.value,
        format=ExportArtifactFormat.JSON_ZIP.value,
        storage_backend=ExportArtifactStorageBackend.LOCAL.value,
        schema_version="1.0",
        requested_by_user_id=uuid4(),
        queued_at=now,
        expires_at=now + timedelta(days=1),
    )


def test_mark_export_artifact_ready_clears_processing_state() -> None:
    artifact = _artifact(status=ExportArtifactStatus.PROCESSING)
    artifact.processing_token = "lease-token"
    artifact.processing_lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    completed_at = datetime.now(UTC)

    changed = mark_export_artifact_ready(artifact, completed_at=completed_at)

    assert artifact.status == ExportArtifactStatus.READY.value
    assert artifact.completed_at == completed_at
    assert artifact.processing_token is None
    assert artifact.processing_lease_expires_at is None
    assert set(changed) == {
        "status",
        "completed_at",
        "processing_token",
        "processing_lease_expires_at",
    }


def test_mark_export_artifact_failed_truncates_detail_and_clears_lease() -> None:
    artifact = _artifact(status=ExportArtifactStatus.PROCESSING)
    artifact.processing_token = "lease-token"
    artifact.processing_lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    failed_at = datetime.now(UTC)

    changed = mark_export_artifact_failed(
        artifact,
        reason_code="generation_failed",
        detail="x" * 300,
        failed_at=failed_at,
    )

    assert artifact.status == ExportArtifactStatus.FAILED.value
    assert artifact.failure_reason_code == "generation_failed"
    assert artifact.failure_detail == "x" * 255
    assert artifact.failed_at == failed_at
    assert artifact.processing_token is None
    assert artifact.processing_lease_expires_at is None
    assert "status" in changed
    assert "failure_detail" in changed


def test_mark_export_artifact_expired_clears_processing_state() -> None:
    artifact = _artifact(status=ExportArtifactStatus.READY)
    artifact.processing_token = "stale-token"
    artifact.processing_lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)

    changed = mark_export_artifact_expired(artifact)

    assert artifact.status == ExportArtifactStatus.EXPIRED.value
    assert artifact.processing_token is None
    assert artifact.processing_lease_expires_at is None
    assert set(changed) == {
        "status",
        "processing_token",
        "processing_lease_expires_at",
    }


def test_clear_export_artifact_storage_metadata_clears_download_fields() -> None:
    artifact = _artifact(status=ExportArtifactStatus.CANCELLED)
    artifact.storage_key = f"exports/{uuid4()}/archive.zip"
    artifact.filename = "archive.zip"
    artifact.content_type = "application/zip"
    artifact.size_bytes = 123
    artifact.checksum_sha256 = "0" * 64

    changed = clear_export_artifact_storage_metadata(artifact)

    assert artifact.storage_key is None
    assert artifact.filename is None
    assert artifact.content_type is None
    assert artifact.size_bytes is None
    assert artifact.checksum_sha256 is None
    assert set(changed) == {
        "storage_key",
        "filename",
        "content_type",
        "size_bytes",
        "checksum_sha256",
    }


def test_cancel_for_subject_erasure_preserves_storage_retry_marker() -> None:
    artifact = _artifact(status=ExportArtifactStatus.READY)
    storage_key = f"exports/{uuid4()}/subject.zip"
    artifact.storage_key = storage_key
    artifact.filename = "subject.zip"
    artifact.content_type = "application/zip"
    artifact.size_bytes = 123
    artifact.checksum_sha256 = "0" * 64
    artifact.failure_detail = "Previous detail"
    artifact.processing_token = "stale-token"
    artifact.processing_lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)

    changed = cancel_export_artifact_for_subject_erasure(artifact)

    assert artifact.status == ExportArtifactStatus.CANCELLED.value
    assert artifact.failure_reason_code == SUBJECT_ERASURE_CANCELLED_EXPORT_REASON
    assert artifact.storage_key == storage_key
    assert artifact.filename is None
    assert artifact.content_type is None
    assert artifact.size_bytes is None
    assert artifact.checksum_sha256 is None
    assert artifact.failure_detail is None
    assert artifact.processing_token is None
    assert artifact.processing_lease_expires_at is None
    assert "storage_key" not in changed
