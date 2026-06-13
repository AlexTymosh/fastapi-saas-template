from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import event, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config.settings import get_settings
from app.memberships.models.membership import Membership
from app.organisations.models.organisation import Organisation
from app.platform.models.platform_staff import PlatformStaff
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.models.privacy_governance import (
    ConsentRecord,
    DataProcessingAuthorization,
    PrivacyNoticeAcceptance,
)
from app.privacy.storage.base import StorageAdapter
from app.privacy.storage.local import LocalStorageAdapter
from app.privacy.storage.s3 import S3CompatibleStorageAdapter

_MEMBERSHIPS_PROVIDER_KEY = "memberships.minimise_subject_link"
_MEMBERSHIPS_TABLE_NAME = "memberships"
_ORGANISATIONS_PROVIDER_KEY = "organisations.review_subject_references"
_ORGANISATIONS_TABLE_NAME = "organisations"
_PLATFORM_STAFF_PROVIDER_KEY = "platform_staff.minimise_subject_or_creator_links"
_PLATFORM_STAFF_TABLE_NAME = "platform_staff"
_DSR_PROVIDER_KEY = "dsr.minimise_workflow_identifiers"
_DSR_TABLE_NAME = "data_subject_requests"
_EXPORT_ARTIFACTS_PROVIDER_KEY = (
    "export_artifacts.delete_object_minimise_subject_or_actor_metadata"
)
_EXPORT_ARTIFACTS_TABLE_NAME = "export_artifacts"
_PRIVACY_AUTHORIZATIONS_PROVIDER_KEY = "privacy_governance.minimise_authorizations"
_PRIVACY_AUTHORIZATIONS_TABLE_NAME = "data_processing_authorizations"
_PRIVACY_CONSENTS_PROVIDER_KEY = "privacy_governance.minimise_consent_records"
_PRIVACY_CONSENTS_TABLE_NAME = "consent_records"
_PRIVACY_NOTICES_PROVIDER_KEY = "privacy_governance.minimise_notice_acceptances"
_PRIVACY_NOTICES_TABLE_NAME = "privacy_notice_acceptances"
_SUBJECT_ERASURE_CANCELLED_EXPORT_REASON = "subject_erasure_requested"
_DEFERRED_EXPORT_OBJECT_DELETIONS_KEY = (
    "privacy_erasure_deferred_export_object_deletions"
)
_DEFERRED_EXPORT_OBJECT_DELETION_HOOKS_KEY = (
    "privacy_erasure_deferred_export_object_deletion_hooks_registered"
)
_logger = logging.getLogger(__name__)


class RemainingInventoryErasureStatus(StrEnum):
    MINIMISED = "minimised"
    ALREADY_MINIMISED = "already_minimised"
    RETAINED_BY_POLICY = "retained_by_policy"
    MANUAL_REVIEW_POLICY = "manual_review_policy"


class RemainingInventoryErasureError(ValueError):
    """Raised when remaining-inventory erasure cannot be applied safely."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class RemainingInventoryErasureResult:
    provider_key: str
    table_name: str
    subject_user_id: UUID
    status: RemainingInventoryErasureStatus
    affected_rows: int
    changed_fields: tuple[str, ...]
    processed_at: datetime

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0


@dataclass(frozen=True, slots=True)
class _DeferredExportObjectDeletion:
    storage_backend: str
    storage_key: str


async def apply_membership_erasure_policy(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_user_id: UUID | None = None,
    now: datetime | None = None,
) -> RemainingInventoryErasureResult:
    """Retain subject memberships while relying on user-profile anonymisation.

    Membership rows are tenant relationship history. Their ``user_id`` is not
    nullable and participates in integrity constraints, so this provider records
    an explicit retain-and-minimise policy instead of deleting or re-parenting
    rows. The user profile provider removes the direct identifiers behind the
    retained key.
    """

    subject_id = _validate_request(request, subject_user_id=subject_user_id)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    await _subject_membership_ids(session, subject_user_id=subject_id)
    return _result(
        provider_key=_MEMBERSHIPS_PROVIDER_KEY,
        table_name=_MEMBERSHIPS_TABLE_NAME,
        subject_user_id=subject_id,
        status=RemainingInventoryErasureStatus.RETAINED_BY_POLICY,
        affected_rows=0,
        changed_fields=(),
        processed_at=reference_now,
    )


async def apply_organisation_erasure_policy(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_user_id: UUID | None = None,
    now: datetime | None = None,
) -> RemainingInventoryErasureResult:
    """Retain tenant-owned organisation records with explicit review policy."""

    subject_id = _validate_request(request, subject_user_id=subject_user_id)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    await _subject_organisation_ids(session, subject_user_id=subject_id)
    return _result(
        provider_key=_ORGANISATIONS_PROVIDER_KEY,
        table_name=_ORGANISATIONS_TABLE_NAME,
        subject_user_id=subject_id,
        status=RemainingInventoryErasureStatus.MANUAL_REVIEW_POLICY,
        affected_rows=0,
        changed_fields=(),
        processed_at=reference_now,
    )


async def minimise_platform_staff_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_user_id: UUID | None = None,
    now: datetime | None = None,
) -> RemainingInventoryErasureResult:
    """Minimise subject-linked platform-staff records without deleting roles."""

    subject_id = _validate_request(request, subject_user_id=subject_user_id)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    rows = await _lock_platform_staff_rows(session, subject_user_id=subject_id)
    affected_rows, changed_fields = _minimise_platform_staff_rows(
        rows,
        subject_user_id=subject_id,
    )
    if affected_rows:
        await session.flush()
    return _result(
        provider_key=_PLATFORM_STAFF_PROVIDER_KEY,
        table_name=_PLATFORM_STAFF_TABLE_NAME,
        subject_user_id=subject_id,
        status=_mutation_status(affected_rows),
        affected_rows=affected_rows,
        changed_fields=changed_fields,
        processed_at=reference_now,
    )


async def minimise_export_artifacts_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_user_id: UUID | None = None,
    now: datetime | None = None,
) -> RemainingInventoryErasureResult:
    """Defer object deletion and minimise export artifact metadata.

    Any processing artifact that references the erasure subject is rejected to
    avoid racing an active worker lease. Subject-owned artifacts with stored
    objects are marked as non-downloadable retry candidates before DSR links
    are cleared. Stored subject export objects are deleted only after the DB
    transaction commits, so rollback cannot leave READY rows pointing at
    deleted objects. The storage key is retained as a retry marker until a
    later cleanup can confirm the object was purged. Actor-only non-processing
    references are minimised without deleting another subject's export object.
    """

    subject_id = _validate_request(request, subject_user_id=subject_user_id)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    rows = await _lock_export_artifact_rows(session, subject_user_id=subject_id)
    _reject_processing_export_artifacts(rows, subject_user_id=subject_id)
    _defer_export_artifact_object_deletions(
        session,
        rows,
        subject_user_id=subject_id,
    )
    affected_rows, changed_fields = _minimise_export_artifact_rows(
        rows,
        subject_user_id=subject_id,
    )
    if affected_rows:
        await session.flush()
    return _result(
        provider_key=_EXPORT_ARTIFACTS_PROVIDER_KEY,
        table_name=_EXPORT_ARTIFACTS_TABLE_NAME,
        subject_user_id=subject_id,
        status=_mutation_status(affected_rows),
        affected_rows=affected_rows,
        changed_fields=changed_fields,
        processed_at=reference_now,
    )


async def minimise_privacy_governance_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_user_id: UUID | None = None,
    now: datetime | None = None,
) -> tuple[RemainingInventoryErasureResult, ...]:
    """Minimise privacy-governance records while retaining compliance evidence."""

    subject_id = _validate_request(request, subject_user_id=subject_user_id)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    authorizations = await _lock_authorization_rows(session, subject_user_id=subject_id)
    await _lock_consent_rows(session, subject_user_id=subject_id)
    notices = await _lock_notice_rows(session, subject_user_id=subject_id)

    auth_affected_rows, auth_changed_fields = _clear_field_on_rows(
        authorizations,
        "source",
    )
    notice_affected_rows, notice_changed_fields = _clear_field_on_rows(
        notices,
        "source",
    )
    if auth_affected_rows or notice_affected_rows:
        await session.flush()

    return (
        _result(
            provider_key=_PRIVACY_AUTHORIZATIONS_PROVIDER_KEY,
            table_name=_PRIVACY_AUTHORIZATIONS_TABLE_NAME,
            subject_user_id=subject_id,
            status=_mutation_status(auth_affected_rows),
            affected_rows=auth_affected_rows,
            changed_fields=auth_changed_fields,
            processed_at=reference_now,
        ),
        _result(
            provider_key=_PRIVACY_CONSENTS_PROVIDER_KEY,
            table_name=_PRIVACY_CONSENTS_TABLE_NAME,
            subject_user_id=subject_id,
            status=RemainingInventoryErasureStatus.RETAINED_BY_POLICY,
            affected_rows=0,
            changed_fields=(),
            processed_at=reference_now,
        ),
        _result(
            provider_key=_PRIVACY_NOTICES_PROVIDER_KEY,
            table_name=_PRIVACY_NOTICES_TABLE_NAME,
            subject_user_id=subject_id,
            status=_mutation_status(notice_affected_rows),
            affected_rows=notice_affected_rows,
            changed_fields=notice_changed_fields,
            processed_at=reference_now,
        ),
    )


async def minimise_dsr_workflow_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_user_id: UUID | None = None,
    now: datetime | None = None,
) -> RemainingInventoryErasureResult:
    """Minimise subject-linked DSR workflow records after core providers run."""

    subject_id = _validate_request(request, subject_user_id=subject_user_id)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    rows = await _lock_dsr_rows(session, subject_user_id=subject_id)
    affected_rows, changed_fields = _minimise_dsr_rows(
        rows,
        subject_user_id=subject_id,
    )
    if affected_rows:
        await session.flush()
    return _result(
        provider_key=_DSR_PROVIDER_KEY,
        table_name=_DSR_TABLE_NAME,
        subject_user_id=subject_id,
        status=_mutation_status(affected_rows),
        affected_rows=affected_rows,
        changed_fields=changed_fields,
        processed_at=reference_now,
    )


def _validate_request(
    request: DataSubjectRequest,
    *,
    subject_user_id: UUID | None,
) -> UUID:
    if request.request_type != DataSubjectRequestType.ERASE.value:
        raise RemainingInventoryErasureError("remaining_erasure_requires_erase_request")
    if request.status != DataSubjectRequestStatus.APPROVED.value:
        raise RemainingInventoryErasureError(
            "remaining_erasure_requires_approved_request"
        )
    effective_subject_user_id = subject_user_id or request.subject_user_id
    if effective_subject_user_id is None:
        raise RemainingInventoryErasureError("remaining_erasure_requires_subject_user")
    return effective_subject_user_id


async def _subject_membership_ids(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[UUID, ...]:
    stmt = select(Membership.id).where(Membership.user_id == subject_user_id)
    return tuple((await session.execute(stmt)).scalars().all())


async def _subject_organisation_ids(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[UUID, ...]:
    stmt = (
        select(Organisation.id)
        .join(Membership, Membership.organisation_id == Organisation.id)
        .where(Membership.user_id == subject_user_id)
        .order_by(Organisation.id.asc())
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _lock_platform_staff_rows(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[PlatformStaff, ...]:
    stmt = (
        select(PlatformStaff)
        .where(
            or_(
                PlatformStaff.user_id == subject_user_id,
                PlatformStaff.created_by_user_id == subject_user_id,
            )
        )
        .order_by(PlatformStaff.created_at.asc(), PlatformStaff.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _lock_export_artifact_rows(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[ExportArtifact, ...]:
    stmt = (
        select(ExportArtifact)
        .where(
            or_(
                ExportArtifact.subject_user_id == subject_user_id,
                ExportArtifact.requester_user_id == subject_user_id,
                ExportArtifact.requested_by_user_id == subject_user_id,
                ExportArtifact.generated_by_user_id == subject_user_id,
            )
        )
        .order_by(ExportArtifact.created_at.asc(), ExportArtifact.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _lock_authorization_rows(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[DataProcessingAuthorization, ...]:
    stmt = (
        select(DataProcessingAuthorization)
        .where(DataProcessingAuthorization.subject_user_id == subject_user_id)
        .order_by(DataProcessingAuthorization.created_at.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _lock_consent_rows(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[ConsentRecord, ...]:
    stmt = (
        select(ConsentRecord)
        .where(ConsentRecord.subject_user_id == subject_user_id)
        .order_by(ConsentRecord.created_at.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _lock_notice_rows(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[PrivacyNoticeAcceptance, ...]:
    stmt = (
        select(PrivacyNoticeAcceptance)
        .where(PrivacyNoticeAcceptance.subject_user_id == subject_user_id)
        .order_by(PrivacyNoticeAcceptance.created_at.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _lock_dsr_rows(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[DataSubjectRequest, ...]:
    stmt = (
        select(DataSubjectRequest)
        .where(
            or_(
                DataSubjectRequest.subject_user_id == subject_user_id,
                DataSubjectRequest.requester_user_id == subject_user_id,
                DataSubjectRequest.reviewer_user_id == subject_user_id,
            )
        )
        .order_by(DataSubjectRequest.created_at.asc(), DataSubjectRequest.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _reject_processing_export_artifacts(
    rows: tuple[ExportArtifact, ...],
    *,
    subject_user_id: UUID,
) -> None:
    del subject_user_id
    has_processing_artifact = any(
        row.status == ExportArtifactStatus.PROCESSING.value for row in rows
    )
    if has_processing_artifact:
        raise RemainingInventoryErasureError(
            "export_artifact_erasure_processing_active"
        )


def _defer_export_artifact_object_deletions(
    session: AsyncSession,
    rows: tuple[ExportArtifact, ...],
    *,
    subject_user_id: UUID,
) -> None:
    deletions = tuple(
        _subject_owned_export_object_deletions(
            rows,
            subject_user_id=subject_user_id,
        )
    )
    if not deletions:
        return
    _register_deferred_export_object_deletions(session, deletions)


def _subject_owned_export_object_deletions(
    rows: tuple[ExportArtifact, ...],
    *,
    subject_user_id: UUID,
) -> tuple[_DeferredExportObjectDeletion, ...]:
    deletions: list[_DeferredExportObjectDeletion] = []
    for row in rows:
        if not _is_subject_owned_export_artifact(
            row,
            subject_user_id=subject_user_id,
        ):
            continue
        if row.storage_key is None:
            continue
        _validate_export_storage_backend(row.storage_backend)
        deletions.append(
            _DeferredExportObjectDeletion(
                storage_backend=row.storage_backend,
                storage_key=row.storage_key,
            )
        )
    return tuple(deletions)


def _register_deferred_export_object_deletions(
    session: AsyncSession,
    deletions: tuple[_DeferredExportObjectDeletion, ...],
) -> None:
    sync_session = session.sync_session
    pending_deletions = sync_session.info.setdefault(
        _DEFERRED_EXPORT_OBJECT_DELETIONS_KEY,
        [],
    )
    pending_deletions.extend(deletions)
    if sync_session.info.get(_DEFERRED_EXPORT_OBJECT_DELETION_HOOKS_KEY):
        return
    event.listen(
        sync_session,
        "after_transaction_end",
        _delete_deferred_export_artifact_objects_after_root_end,
    )
    event.listen(
        sync_session,
        "after_rollback",
        _discard_deferred_export_artifact_objects,
    )
    event.listen(
        sync_session,
        "after_soft_rollback",
        _discard_deferred_export_artifact_objects_after_soft_rollback,
    )
    sync_session.info[_DEFERRED_EXPORT_OBJECT_DELETION_HOOKS_KEY] = True


def _delete_deferred_export_artifact_objects_after_root_end(
    sync_session: Session,
    transaction: object,
) -> None:
    if getattr(transaction, "parent", None) is not None:
        return

    deletions = tuple(sync_session.info.pop(_DEFERRED_EXPORT_OBJECT_DELETIONS_KEY, ()))
    if not deletions:
        return

    storage_by_backend: dict[str, StorageAdapter] = {}
    for deletion in deletions:
        try:
            storage = storage_by_backend.get(deletion.storage_backend)
            if storage is None:
                storage = _build_export_storage_adapter(deletion.storage_backend)
                storage_by_backend[deletion.storage_backend] = storage
            storage.delete(deletion.storage_key)
        except Exception:
            _logger.exception(
                "Failed to delete export artifact object after erasure commit"
            )


def _discard_deferred_export_artifact_objects(sync_session: Session) -> None:
    sync_session.info.pop(_DEFERRED_EXPORT_OBJECT_DELETIONS_KEY, None)


def _discard_deferred_export_artifact_objects_after_soft_rollback(
    sync_session: Session,
    previous_transaction: object,
) -> None:
    del previous_transaction
    _discard_deferred_export_artifact_objects(sync_session)


def _validate_export_storage_backend(backend: str) -> None:
    if backend in {
        ExportArtifactStorageBackend.LOCAL.value,
        ExportArtifactStorageBackend.S3_COMPATIBLE.value,
    }:
        return
    raise RemainingInventoryErasureError("export_artifact_unknown_storage_backend")


def _is_subject_owned_export_artifact(
    row: ExportArtifact,
    *,
    subject_user_id: UUID,
) -> bool:
    return (
        row.subject_user_id == subject_user_id
        or row.requester_user_id == subject_user_id
    )


def _build_export_storage_adapter(backend: str) -> StorageAdapter:
    exports = get_settings().privacy_exports
    if backend == ExportArtifactStorageBackend.LOCAL.value:
        return LocalStorageAdapter(
            exports.local_storage_path,
            exports.local_signing_secret,
        )
    if backend == ExportArtifactStorageBackend.S3_COMPATIBLE.value:
        return S3CompatibleStorageAdapter(
            bucket_name=exports.s3_bucket_name or "",
            region_name=exports.s3_region_name or "",
            endpoint_url=exports.s3_endpoint_url,
            access_key_id=_optional_secret_value(exports.s3_access_key_id),
            secret_access_key=_optional_secret_value(exports.s3_secret_access_key),
            key_prefix=exports.s3_key_prefix,
            server_side_encryption=exports.s3_server_side_encryption,
            sse_kms_key_id=exports.s3_sse_kms_key_id,
            addressing_style=exports.s3_addressing_style,
            connect_timeout_seconds=exports.s3_connect_timeout_seconds,
            read_timeout_seconds=exports.s3_read_timeout_seconds,
            max_attempts=exports.s3_max_attempts,
        )
    raise RemainingInventoryErasureError("export_artifact_unknown_storage_backend")


def _optional_secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _minimise_platform_staff_rows(
    rows: tuple[PlatformStaff, ...],
    *,
    subject_user_id: UUID,
) -> tuple[int, tuple[str, ...]]:
    affected_rows = 0
    changed_fields: set[str] = set()
    for row in rows:
        row_changed_fields: list[str] = []
        is_subject_staff_record = row.user_id == subject_user_id
        is_subject_created_record = row.created_by_user_id == subject_user_id
        if is_subject_created_record:
            _set_if_changed(row, "created_by_user_id", None, row_changed_fields)
        if is_subject_staff_record or is_subject_created_record:
            _set_if_changed(row, "suspended_reason", None, row_changed_fields)
        if row_changed_fields:
            affected_rows += 1
            changed_fields.update(row_changed_fields)
    return affected_rows, tuple(sorted(changed_fields))


def _minimise_export_artifact_rows(
    rows: tuple[ExportArtifact, ...],
    *,
    subject_user_id: UUID,
) -> tuple[int, tuple[str, ...]]:
    affected_rows = 0
    changed_fields: set[str] = set()
    for row in rows:
        row_changed_fields: list[str] = []
        is_subject_owned_artifact = _is_subject_owned_export_artifact(
            row,
            subject_user_id=subject_user_id,
        )
        should_mark_retryable = is_subject_owned_artifact and (
            row.storage_key is not None
            or row.status in _CANCELLED_EXPORT_ERASURE_STATUSES
        )
        if should_mark_retryable:
            _set_if_changed(
                row,
                "status",
                ExportArtifactStatus.CANCELLED.value,
                row_changed_fields,
            )
            _set_if_changed(
                row,
                "failure_reason_code",
                _SUBJECT_ERASURE_CANCELLED_EXPORT_REASON,
                row_changed_fields,
            )
        for field_name in (
            "subject_user_id",
            "requester_user_id",
            "requested_by_user_id",
            "generated_by_user_id",
        ):
            if getattr(row, field_name) == subject_user_id:
                _set_if_changed(row, field_name, None, row_changed_fields)
        if is_subject_owned_artifact:
            for field_name in (
                "filename",
                "content_type",
                "size_bytes",
                "checksum_sha256",
                "failure_detail",
                "processing_token",
                "processing_lease_expires_at",
            ):
                _set_if_changed(row, field_name, None, row_changed_fields)
        if row_changed_fields:
            affected_rows += 1
            changed_fields.update(row_changed_fields)
    return affected_rows, tuple(sorted(changed_fields))


_CANCELLED_EXPORT_ERASURE_STATUSES = frozenset(
    {
        ExportArtifactStatus.QUEUED.value,
        ExportArtifactStatus.READY.value,
    }
)


def _minimise_dsr_rows(
    rows: tuple[DataSubjectRequest, ...],
    *,
    subject_user_id: UUID,
) -> tuple[int, tuple[str, ...]]:
    affected_rows = 0
    changed_fields: set[str] = set()
    for row in rows:
        row_changed_fields: list[str] = []
        is_subject_or_requester_row = (
            row.requester_user_id == subject_user_id
            or row.subject_user_id == subject_user_id
        )
        for field_name in ("requester_user_id", "subject_user_id", "reviewer_user_id"):
            if getattr(row, field_name) == subject_user_id:
                _set_if_changed(row, field_name, None, row_changed_fields)
        if is_subject_or_requester_row:
            for field_name in (
                "requester_note",
                "internal_note",
                "execution_failure_detail",
                "idempotency_key_hash",
                "idempotency_fingerprint",
                "idempotency_key_expires_at",
            ):
                _set_if_changed(row, field_name, None, row_changed_fields)
        if row_changed_fields:
            affected_rows += 1
            changed_fields.update(row_changed_fields)
    return affected_rows, tuple(sorted(changed_fields))


def _clear_field_on_rows(
    rows: tuple[object, ...],
    field_name: str,
) -> tuple[int, tuple[str, ...]]:
    affected_rows = 0
    changed_fields: set[str] = set()
    for row in rows:
        row_changed_fields: list[str] = []
        _set_if_changed(row, field_name, None, row_changed_fields)
        if row_changed_fields:
            affected_rows += 1
            changed_fields.update(row_changed_fields)
    return affected_rows, tuple(sorted(changed_fields))


def _set_if_changed(
    row: object,
    field_name: str,
    target_value: object,
    changed_fields: list[str],
) -> None:
    if getattr(row, field_name) == target_value:
        return
    setattr(row, field_name, target_value)
    changed_fields.append(field_name)


def _mutation_status(affected_rows: int) -> RemainingInventoryErasureStatus:
    if affected_rows:
        return RemainingInventoryErasureStatus.MINIMISED
    return RemainingInventoryErasureStatus.ALREADY_MINIMISED


def _result(
    *,
    provider_key: str,
    table_name: str,
    subject_user_id: UUID,
    status: RemainingInventoryErasureStatus,
    affected_rows: int,
    changed_fields: tuple[str, ...],
    processed_at: datetime,
) -> RemainingInventoryErasureResult:
    return RemainingInventoryErasureResult(
        provider_key=provider_key,
        table_name=table_name,
        subject_user_id=subject_user_id,
        status=status,
        affected_rows=affected_rows,
        changed_fields=changed_fields,
        processed_at=processed_at,
    )


def _normalise_reference_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
