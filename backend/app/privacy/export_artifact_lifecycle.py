from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.privacy.models.export_artifact import ExportArtifact, ExportArtifactStatus

SUBJECT_ERASURE_CANCELLED_EXPORT_REASON = "subject_erasure_requested"

_CONTENT_METADATA_FIELDS = (
    "filename",
    "content_type",
    "size_bytes",
    "checksum_sha256",
)
_STORAGE_METADATA_FIELDS = ("storage_key", *_CONTENT_METADATA_FIELDS)
_SUBJECT_FILE_METADATA_FIELDS = (
    *_CONTENT_METADATA_FIELDS,
    "failure_detail",
    "processing_token",
    "processing_lease_expires_at",
)


def mark_export_artifact_ready(
    artifact: ExportArtifact,
    *,
    completed_at: datetime | None = None,
) -> tuple[str, ...]:
    """Apply the successful terminal transition for a generated artifact."""

    changed_fields: list[str] = []
    _set_if_changed(
        artifact,
        "status",
        ExportArtifactStatus.READY.value,
        changed_fields,
    )
    _set_if_changed(
        artifact,
        "completed_at",
        completed_at or datetime.now(UTC),
        changed_fields,
    )
    _clear_fields(
        artifact,
        ("processing_token", "processing_lease_expires_at"),
        changed_fields,
    )
    return tuple(changed_fields)


def mark_export_artifact_failed(
    artifact: ExportArtifact,
    *,
    reason_code: str,
    detail: str,
    failed_at: datetime | None = None,
) -> tuple[str, ...]:
    """Apply a non-downloadable failure while retaining storage retry state."""

    changed_fields: list[str] = []
    _set_if_changed(
        artifact,
        "status",
        ExportArtifactStatus.FAILED.value,
        changed_fields,
    )
    _set_if_changed(artifact, "failure_reason_code", reason_code, changed_fields)
    _set_if_changed(artifact, "failure_detail", detail[:255], changed_fields)
    _set_if_changed(
        artifact,
        "failed_at",
        failed_at or datetime.now(UTC),
        changed_fields,
    )
    _clear_fields(
        artifact,
        ("processing_token", "processing_lease_expires_at"),
        changed_fields,
    )
    return tuple(changed_fields)


def mark_export_artifact_expired(
    artifact: ExportArtifact,
) -> tuple[str, ...]:
    """Make the artifact non-downloadable before storage purge is allowed.

    Retention cleanup keeps storage metadata as a retry marker until a later
    pass can purge the stored object from a committed non-downloadable DB state.
    """

    changed_fields: list[str] = []
    _set_if_changed(
        artifact,
        "status",
        ExportArtifactStatus.EXPIRED.value,
        changed_fields,
    )
    _clear_fields(
        artifact,
        ("processing_token", "processing_lease_expires_at"),
        changed_fields,
    )
    return tuple(changed_fields)


def cancel_export_artifact_for_subject_erasure(
    artifact: ExportArtifact,
    *,
    reason_code: str = SUBJECT_ERASURE_CANCELLED_EXPORT_REASON,
) -> tuple[str, ...]:
    """Make a subject-owned export artifact non-downloadable after erasure.

    ``storage_key`` is intentionally preserved as a retry marker until the
    retention cleanup confirms that the external object has been purged.
    """

    changed_fields: list[str] = []
    _set_if_changed(
        artifact,
        "status",
        ExportArtifactStatus.CANCELLED.value,
        changed_fields,
    )
    _set_if_changed(artifact, "failure_reason_code", reason_code, changed_fields)
    changed_fields.extend(clear_export_artifact_subject_file_metadata(artifact))
    return tuple(_unique_in_order(changed_fields))


def clear_export_artifact_storage_metadata(
    artifact: ExportArtifact,
) -> tuple[str, ...]:
    """Clear the storage object reference and derived file metadata."""

    changed_fields: list[str] = []
    _clear_fields(artifact, _STORAGE_METADATA_FIELDS, changed_fields)
    return tuple(changed_fields)


def clear_export_artifact_subject_file_metadata(
    artifact: ExportArtifact,
) -> tuple[str, ...]:
    """Clear subject-owned file metadata while preserving storage retry state."""

    changed_fields: list[str] = []
    _clear_fields(artifact, _SUBJECT_FILE_METADATA_FIELDS, changed_fields)
    return tuple(changed_fields)


def _clear_fields(
    artifact: ExportArtifact,
    field_names: tuple[str, ...],
    changed_fields: list[str],
) -> None:
    for field_name in field_names:
        _set_if_changed(artifact, field_name, None, changed_fields)


def _set_if_changed(
    artifact: ExportArtifact,
    field_name: str,
    value: Any,
    changed_fields: list[str],
) -> None:
    if getattr(artifact, field_name) == value:
        return
    setattr(artifact, field_name, value)
    changed_fields.append(field_name)


def _unique_in_order(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
