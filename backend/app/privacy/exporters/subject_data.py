from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditEvent, AuditTargetType
from app.invites.models.invite import Invite
from app.memberships.models.membership import Membership
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent
from app.platform.models.platform_staff import PlatformStaff
from app.privacy.exporters.base import ExportContext
from app.privacy.models.data_subject_request import DataSubjectRequest
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactStatus,
)
from app.privacy.models.privacy_governance import (
    ConsentRecord,
    DataProcessingAuthorization,
    PrivacyNoticeAcceptance,
    ProcessingPurpose,
)
from app.privacy.providers.base import (
    PrivacyExportRecord,
    PrivacyExportRecordKind,
    PrivacyProviderContext,
)
from app.users.models.user import User


class SubjectDataExportError(ValueError):
    """Raised when an approved DSR cannot be exported safely."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class _BaseSubjectExportProvider:
    provider_key: str
    table_name: str

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        raise NotImplementedError

    def _record(
        self,
        payload: Mapping[str, object],
        *,
        record_kind: PrivacyExportRecordKind = PrivacyExportRecordKind.DATA,
        redacted_fields: Sequence[str] = (),
    ) -> PrivacyExportRecord:
        return PrivacyExportRecord(
            provider_key=self.provider_key,
            table_name=self.table_name,
            record_kind=record_kind,
            payload={key: _json_value(value) for key, value in payload.items()},
            redacted_fields=tuple(redacted_fields),
        )


class UserProfileExportProvider(_BaseSubjectExportProvider):
    provider_key = "users.profile"
    table_name = "users"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        user = await _get_subject_user(self.session, context.subject_user_id)
        if user is None:
            raise SubjectDataExportError("subject_user_not_found")

        yield self._record(
            {
                "id": user.id,
                "external_auth_id": user.external_auth_id,
                "email": user.email,
                "email_verified": user.email_verified,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "onboarding_completed": user.onboarding_completed,
                "status": user.status,
                "suspended_at": user.suspended_at,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
            },
            redacted_fields=("suspended_reason",),
        )


class MembershipsBySubjectExportProvider(_BaseSubjectExportProvider):
    provider_key = "memberships.by_subject"
    table_name = "memberships"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(Membership)
            .where(Membership.user_id == context.subject_user_id)
            .order_by(Membership.created_at.asc(), Membership.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            yield self._record(
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "organisation_id": row.organisation_id,
                    "role": row.role,
                    "is_active": row.is_active,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )


class OrganisationsBySubjectMembershipExportProvider(_BaseSubjectExportProvider):
    provider_key = "organisations.by_subject_membership"
    table_name = "organisations"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(Organisation)
            .join(Membership, Membership.organisation_id == Organisation.id)
            .where(Membership.user_id == context.subject_user_id)
            .order_by(Organisation.created_at.asc(), Organisation.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().unique().all()
        for row in rows:
            yield self._record(
                {
                    "id": row.id,
                    "name": row.name,
                    "slug": row.slug,
                    "status": row.status,
                    "deleted_at": row.deleted_at,
                    "suspended_at": row.suspended_at,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                },
                redacted_fields=("suspended_reason",),
            )


class InvitesBySubjectExportProvider(_BaseSubjectExportProvider):
    provider_key = "invites.by_subject_email_or_revoker"
    table_name = "invites"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        conditions = [Invite.revoked_by_user_id == context.subject_user_id]
        subject_email = await _get_subject_email(self.session, context.subject_user_id)
        if subject_email is not None:
            conditions.append(func.lower(Invite.email) == subject_email.lower())

        stmt = (
            select(Invite)
            .where(or_(*conditions))
            .order_by(Invite.created_at.asc(), Invite.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            if self._is_revoker_only_record(row, subject_email):
                yield self._revoker_reference_record(row)
                continue
            yield self._subject_invite_record(row, context)

    @staticmethod
    def _is_revoker_only_record(row: Invite, subject_email: str | None) -> bool:
        if row.revoked_by_user_id is None:
            return False
        if subject_email is None:
            return True
        return row.email.strip().lower() != subject_email

    def _subject_invite_record(
        self, row: Invite, context: PrivacyProviderContext
    ) -> PrivacyExportRecord:
        payload: dict[str, object] = {
            "id": row.id,
            "email": row.email,
            "organisation_id": row.organisation_id,
            "role": row.role,
            "status": row.status,
            "expires_at": row.expires_at,
            "revoked_at": row.revoked_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        redacted_fields = ["token_hash"]
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="revoked_by_user_id",
            actor_user_id=row.revoked_by_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_revoker",
        )
        return self._record(payload, redacted_fields=tuple(redacted_fields))

    def _revoker_reference_record(self, row: Invite) -> PrivacyExportRecord:
        return self._record(
            {
                "id": row.id,
                "revoked_by_user_id": row.revoked_by_user_id,
                "status": row.status,
                "revoked_at": row.revoked_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
            record_kind=PrivacyExportRecordKind.REFERENCE,
            redacted_fields=(
                "email",
                "organisation_id",
                "role",
                "expires_at",
                "token_hash",
            ),
        )


class OutboxSubjectReferencesExportProvider(_BaseSubjectExportProvider):
    provider_key = "outbox.subject_references"
    table_name = "outbox_events"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        conditions = []
        invite_ids = await _get_subject_invite_ids(
            self.session, context.subject_user_id
        )
        if invite_ids:
            conditions.append(OutboxEvent.aggregate_id.in_(invite_ids))

        subject_email = await _get_subject_email(self.session, context.subject_user_id)
        if subject_email is not None:
            conditions.append(
                OutboxEvent.payload_json["email"].as_string() == subject_email
            )

        if not conditions:
            return

        stmt = (
            select(OutboxEvent)
            .where(or_(*conditions))
            .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            payload_reference, redacted_payload_fields = _outbox_payload_reference(
                row.payload_json
            )
            redacted_fields = ("last_error", *redacted_payload_fields)
            yield self._record(
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "aggregate_type": row.aggregate_type,
                    "aggregate_id": row.aggregate_id,
                    "status": row.status,
                    "attempts": row.attempts,
                    "max_attempts": row.max_attempts,
                    "next_attempt_at": row.next_attempt_at,
                    "locked_at": row.locked_at,
                    "processed_at": row.processed_at,
                    "payload_reference": payload_reference,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                },
                record_kind=PrivacyExportRecordKind.REFERENCE,
                redacted_fields=redacted_fields,
            )


class AuditSubjectEventsExportProvider(_BaseSubjectExportProvider):
    provider_key = "audit.subject_actor_or_target_join_events"
    table_name = "audit_events"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        conditions = await _audit_subject_conditions(
            self.session, context.subject_user_id
        )
        stmt = (
            select(AuditEvent)
            .where(or_(*conditions))
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            yield self._audit_record(row, context)

    def _audit_record(
        self, row: AuditEvent, context: PrivacyProviderContext
    ) -> PrivacyExportRecord:
        metadata, redacted_metadata = _safe_audit_metadata(row.metadata_json)
        payload: dict[str, object] = {
            "id": row.id,
            "category": row.category,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "metadata_json": metadata,
            "created_at": row.created_at,
        }
        redacted_fields = []
        if row.reason is not None:
            redacted_fields.append("reason")
        if row.legal_hold_until is not None:
            redacted_fields.append("legal_hold_until")
        redacted_fields.extend(redacted_metadata)

        if row.actor_user_id == context.subject_user_id:
            payload["actor_user_id"] = row.actor_user_id
            payload["ip_address"] = row.ip_address
            payload["user_agent"] = row.user_agent
        else:
            payload["has_actor"] = row.actor_user_id is not None
            redacted_fields.extend(("actor_user_id", "ip_address", "user_agent"))

        return self._record(payload, redacted_fields=tuple(redacted_fields))


class PlatformStaffBySubjectExportProvider(_BaseSubjectExportProvider):
    provider_key = "platform_staff.by_subject_or_creator"
    table_name = "platform_staff"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(PlatformStaff)
            .where(
                or_(
                    PlatformStaff.user_id == context.subject_user_id,
                    PlatformStaff.created_by_user_id == context.subject_user_id,
                )
            )
            .order_by(PlatformStaff.created_at.asc(), PlatformStaff.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            if self._is_creator_only_record(row, context):
                yield self._creator_reference_record(row)
                continue
            yield self._subject_staff_record(row, context)

    @staticmethod
    def _is_creator_only_record(
        row: PlatformStaff, context: PrivacyProviderContext
    ) -> bool:
        return (
            row.created_by_user_id == context.subject_user_id
            and row.user_id != context.subject_user_id
        )

    def _subject_staff_record(
        self, row: PlatformStaff, context: PrivacyProviderContext
    ) -> PrivacyExportRecord:
        payload: dict[str, object] = {
            "id": row.id,
            "user_id": row.user_id,
            "role": row.role,
            "status": row.status,
            "suspended_at": row.suspended_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        redacted_fields = ["suspended_reason"]
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="created_by_user_id",
            actor_user_id=row.created_by_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_creator",
        )
        return self._record(payload, redacted_fields=tuple(redacted_fields))

    def _creator_reference_record(self, row: PlatformStaff) -> PrivacyExportRecord:
        return self._record(
            {
                "id": row.id,
                "created_by_user_id": row.created_by_user_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
            record_kind=PrivacyExportRecordKind.REFERENCE,
            redacted_fields=(
                "user_id",
                "role",
                "status",
                "suspended_at",
                "suspended_reason",
            ),
        )


class DsrWorkflowRecordsExportProvider(_BaseSubjectExportProvider):
    provider_key = "dsr.workflow_records"
    table_name = "data_subject_requests"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(DataSubjectRequest)
            .where(
                or_(
                    DataSubjectRequest.subject_user_id == context.subject_user_id,
                    DataSubjectRequest.requester_user_id == context.subject_user_id,
                    DataSubjectRequest.reviewer_user_id == context.subject_user_id,
                )
            )
            .order_by(DataSubjectRequest.created_at.asc(), DataSubjectRequest.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            if self._is_reviewer_only_record(row, context):
                yield self._reviewer_reference_record(row)
                continue
            yield self._subject_request_record(row, context)

    @staticmethod
    def _is_reviewer_only_record(
        row: DataSubjectRequest, context: PrivacyProviderContext
    ) -> bool:
        return (
            row.reviewer_user_id == context.subject_user_id
            and row.subject_user_id != context.subject_user_id
            and row.requester_user_id != context.subject_user_id
        )

    def _subject_request_record(
        self, row: DataSubjectRequest, context: PrivacyProviderContext
    ) -> PrivacyExportRecord:
        payload: dict[str, object] = {
            "id": row.id,
            "request_type": row.request_type,
            "status": row.status,
            "execution_status": row.execution_status,
            "requester_role": row.requester_role,
            "representative_status": row.representative_status,
            "representative_relationship": row.representative_relationship,
            "representative_authority_note": row.representative_authority_note,
            "representative_verified_at": row.representative_verified_at,
            "representative_rejection_reason_code": (
                row.representative_rejection_reason_code
            ),
            "submitted_at": row.submitted_at,
            "acknowledged_at": row.acknowledged_at,
            "reviewed_at": row.reviewed_at,
            "decided_at": row.decided_at,
            "fulfilled_at": row.fulfilled_at,
            "cancelled_at": row.cancelled_at,
            "execution_started_at": row.execution_started_at,
            "execution_completed_at": row.execution_completed_at,
            "execution_failed_at": row.execution_failed_at,
            "execution_failure_reason_code": row.execution_failure_reason_code,
            "decision_reason_code": row.decision_reason_code,
            "rejection_reason_code": row.rejection_reason_code,
            "extension_reason_code": row.extension_reason_code,
            "requester_note": row.requester_note,
            "due_at": row.due_at,
            "extended_until": row.extended_until,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        redacted_fields = [
            "internal_note",
            "idempotency_key_hash",
            "idempotency_fingerprint",
            "idempotency_key_expires_at",
            "execution_failure_detail",
        ]
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="requester_user_id",
            actor_user_id=row.requester_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_requester",
        )
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="subject_user_id",
            actor_user_id=row.subject_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_subject",
        )
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="reviewer_user_id",
            actor_user_id=row.reviewer_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_reviewer",
        )
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="representative_verified_by_user_id",
            actor_user_id=row.representative_verified_by_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_representative_verifier",
        )

        return self._record(payload, redacted_fields=tuple(redacted_fields))

    def _reviewer_reference_record(
        self, row: DataSubjectRequest
    ) -> PrivacyExportRecord:
        return self._record(
            {
                "id": row.id,
                "reviewer_user_id": row.reviewer_user_id,
                "status": row.status,
                "execution_status": row.execution_status,
                "reviewed_at": row.reviewed_at,
                "decided_at": row.decided_at,
                "fulfilled_at": row.fulfilled_at,
                "cancelled_at": row.cancelled_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
            record_kind=PrivacyExportRecordKind.REFERENCE,
            redacted_fields=(
                "request_type",
                "requester_user_id",
                "subject_user_id",
                "submitted_at",
                "acknowledged_at",
                "due_at",
                "extended_until",
                "decision_reason_code",
                "rejection_reason_code",
                "extension_reason_code",
                "requester_note",
                "requester_role",
                "representative_status",
                "representative_relationship",
                "representative_authority_note",
                "representative_verified_at",
                "representative_verified_by_user_id",
                "representative_rejection_reason_code",
                "internal_note",
                "idempotency_key_hash",
                "idempotency_fingerprint",
                "idempotency_key_expires_at",
                "execution_failure_detail",
                "execution_failure_reason_code",
            ),
        )


class ExportArtifactMetadataExportProvider(_BaseSubjectExportProvider):
    provider_key = "export_artifacts.subject_or_actor_metadata"
    table_name = "export_artifacts"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(ExportArtifact)
            .where(
                and_(
                    ExportArtifact.status == ExportArtifactStatus.READY.value,
                    or_(
                        ExportArtifact.subject_user_id == context.subject_user_id,
                        ExportArtifact.requester_user_id == context.subject_user_id,
                        ExportArtifact.requested_by_user_id == context.subject_user_id,
                        ExportArtifact.generated_by_user_id == context.subject_user_id,
                    ),
                )
            )
            .order_by(ExportArtifact.created_at.asc(), ExportArtifact.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            if self._is_actor_only_record(row, context):
                yield self._actor_reference_record(row, context)
                continue
            yield self._subject_artifact_record(row, context)

    @staticmethod
    def _is_actor_only_record(
        row: ExportArtifact, context: PrivacyProviderContext
    ) -> bool:
        return (
            row.subject_user_id != context.subject_user_id
            and row.requester_user_id != context.subject_user_id
            and (
                row.requested_by_user_id == context.subject_user_id
                or row.generated_by_user_id == context.subject_user_id
            )
        )

    def _subject_artifact_record(
        self, row: ExportArtifact, context: PrivacyProviderContext
    ) -> PrivacyExportRecord:
        payload: dict[str, object] = {
            "id": row.id,
            "data_subject_request_id": row.data_subject_request_id,
            "subject_user_id": row.subject_user_id,
            "requester_user_id": row.requester_user_id,
            "status": row.status,
            "format": row.format,
            "storage_backend": row.storage_backend,
            "filename": row.filename,
            "content_type": row.content_type,
            "size_bytes": row.size_bytes,
            "checksum_sha256": row.checksum_sha256,
            "schema_version": row.schema_version,
            "failure_reason_code": row.failure_reason_code,
            "queued_at": row.queued_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "failed_at": row.failed_at,
            "expires_at": row.expires_at,
            "download_url_issued_at": row.download_url_issued_at,
            "download_url_issue_count": row.download_url_issue_count,
            "downloaded_at": row.downloaded_at,
            "download_count": row.download_count,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        redacted_fields = [
            "storage_key",
            "processing_token",
            "processing_lease_expires_at",
            "failure_detail",
        ]
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="requested_by_user_id",
            actor_user_id=row.requested_by_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_requested_by",
        )
        _include_or_minimise_actor_field(
            payload,
            redacted_fields,
            field_name="generated_by_user_id",
            actor_user_id=row.generated_by_user_id,
            subject_user_id=context.subject_user_id,
            presence_field="has_generated_by",
        )
        return self._record(payload, redacted_fields=tuple(redacted_fields))

    def _actor_reference_record(
        self, row: ExportArtifact, context: PrivacyProviderContext
    ) -> PrivacyExportRecord:
        requested_by_user_id = (
            row.requested_by_user_id
            if row.requested_by_user_id == context.subject_user_id
            else None
        )
        generated_by_user_id = (
            row.generated_by_user_id
            if row.generated_by_user_id == context.subject_user_id
            else None
        )
        return self._record(
            {
                "id": row.id,
                "requested_by_user_id": requested_by_user_id,
                "generated_by_user_id": generated_by_user_id,
                "status": row.status,
                "format": row.format,
                "storage_backend": row.storage_backend,
                "failure_reason_code": row.failure_reason_code,
                "queued_at": row.queued_at,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "failed_at": row.failed_at,
                "expires_at": row.expires_at,
                "download_url_issued_at": row.download_url_issued_at,
                "download_url_issue_count": row.download_url_issue_count,
                "downloaded_at": row.downloaded_at,
                "download_count": row.download_count,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
            record_kind=PrivacyExportRecordKind.REFERENCE,
            redacted_fields=(
                "data_subject_request_id",
                "subject_user_id",
                "requester_user_id",
                "filename",
                "content_type",
                "size_bytes",
                "checksum_sha256",
                "schema_version",
                "storage_key",
                "processing_token",
                "processing_lease_expires_at",
                "failure_detail",
            ),
        )


class ProcessingAuthorizationsExportProvider(_BaseSubjectExportProvider):
    provider_key = "privacy_governance.authorizations"
    table_name = "data_processing_authorizations"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(DataProcessingAuthorization, ProcessingPurpose)
            .join(
                ProcessingPurpose,
                DataProcessingAuthorization.purpose_id == ProcessingPurpose.id,
            )
            .where(
                DataProcessingAuthorization.subject_user_id == context.subject_user_id
            )
            .order_by(
                DataProcessingAuthorization.created_at.asc(),
                DataProcessingAuthorization.id.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        for authorization, purpose in rows:
            yield self._record(
                {
                    "id": authorization.id,
                    "subject_user_id": authorization.subject_user_id,
                    "purpose_id": authorization.purpose_id,
                    "purpose": _purpose_payload(purpose),
                    "lawful_basis": authorization.lawful_basis,
                    "special_category_condition": (
                        authorization.special_category_condition
                    ),
                    "active": authorization.active,
                    "source": authorization.source,
                    "valid_from": authorization.valid_from,
                    "valid_until": authorization.valid_until,
                    "revoked_at": authorization.revoked_at,
                    "created_at": authorization.created_at,
                    "updated_at": authorization.updated_at,
                }
            )


class ConsentRecordsExportProvider(_BaseSubjectExportProvider):
    provider_key = "privacy_governance.consent_records"
    table_name = "consent_records"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(ConsentRecord, ProcessingPurpose)
            .join(ProcessingPurpose, ConsentRecord.purpose_id == ProcessingPurpose.id)
            .where(ConsentRecord.subject_user_id == context.subject_user_id)
            .order_by(ConsentRecord.created_at.asc(), ConsentRecord.id.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        for consent, purpose in rows:
            yield self._record(
                {
                    "id": consent.id,
                    "subject_user_id": consent.subject_user_id,
                    "purpose_id": consent.purpose_id,
                    "purpose": _purpose_payload(purpose),
                    "authorization_id": consent.authorization_id,
                    "privacy_notice_version": consent.privacy_notice_version,
                    "granted_at": consent.granted_at,
                    "withdrawn_at": consent.withdrawn_at,
                    "withdrawal_reason_code": consent.withdrawal_reason_code,
                    "created_at": consent.created_at,
                    "updated_at": consent.updated_at,
                }
            )


class PrivacyNoticeAcceptancesExportProvider(_BaseSubjectExportProvider):
    provider_key = "privacy_governance.notice_acceptances"
    table_name = "privacy_notice_acceptances"

    async def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]:
        stmt = (
            select(PrivacyNoticeAcceptance)
            .where(PrivacyNoticeAcceptance.subject_user_id == context.subject_user_id)
            .order_by(
                PrivacyNoticeAcceptance.accepted_at.asc(),
                PrivacyNoticeAcceptance.id.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            yield self._record(
                {
                    "id": row.id,
                    "subject_user_id": row.subject_user_id,
                    "notice_version": row.notice_version,
                    "accepted_at": row.accepted_at,
                    "source": row.source,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )


_EXPORT_PROVIDER_TYPES: tuple[type[_BaseSubjectExportProvider], ...] = (
    UserProfileExportProvider,
    MembershipsBySubjectExportProvider,
    OrganisationsBySubjectMembershipExportProvider,
    InvitesBySubjectExportProvider,
    OutboxSubjectReferencesExportProvider,
    AuditSubjectEventsExportProvider,
    PlatformStaffBySubjectExportProvider,
    DsrWorkflowRecordsExportProvider,
    ExportArtifactMetadataExportProvider,
    ProcessingAuthorizationsExportProvider,
    ConsentRecordsExportProvider,
    PrivacyNoticeAcceptancesExportProvider,
)


class CrossTableSubjectDataExporter:
    """Build a DSR export from the concrete privacy export providers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def export_subject_data(self, context: ExportContext) -> dict[str, object]:
        if context.subject_user_id is None:
            raise SubjectDataExportError("subject_user_missing")

        provider_context = PrivacyProviderContext(
            data_subject_request_id=context.data_subject_request_id,
            subject_user_id=context.subject_user_id,
            requester_user_id=context.requester_user_id,
            schema_version=context.schema_version,
        )
        data: dict[str, list[dict[str, object]]] = {}
        redaction_notices: list[dict[str, object]] = []
        record_count = 0

        for provider in self._providers():
            provider_records: list[dict[str, object]] = []
            try:
                async for record in provider.iter_export_records(provider_context):
                    provider_records.append(_serialise_record(record))
                    record_count += 1
                    if record.redacted_fields:
                        redaction_notices.append(
                            {
                                "provider_key": record.provider_key,
                                "table_name": record.table_name,
                                "redacted_fields": list(record.redacted_fields),
                                "reason_code": "non_exportable_or_review_required",
                            }
                        )
            except SubjectDataExportError:
                raise
            except Exception as exc:
                raise SubjectDataExportError("export_provider_failed") from exc
            data[provider.provider_key] = provider_records

        return {
            "schema_version": context.schema_version,
            "generated_at": context.generated_at.isoformat(),
            "data_subject_request_id": str(context.data_subject_request_id),
            "subject_user_id": str(context.subject_user_id),
            "requester_user_id": (
                str(context.requester_user_id) if context.requester_user_id else None
            ),
            "request_type": context.request_type,
            "request_status": context.request_status,
            "artifact_id": str(context.artifact_id),
            "manifest": {
                "format": "privacy_subject_export",
                "provider_count": len(data),
                "record_count": record_count,
                "providers": list(data.keys()),
                "redaction_notices": redaction_notices,
            },
            "data": data,
        }

    def _providers(self) -> list[_BaseSubjectExportProvider]:
        return [provider_type(self.session) for provider_type in _EXPORT_PROVIDER_TYPES]


async def _get_subject_user(
    session: AsyncSession, subject_user_id: UUID
) -> User | None:
    stmt = select(User).where(User.id == subject_user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _get_subject_email(
    session: AsyncSession, subject_user_id: UUID
) -> str | None:
    user = await _get_subject_user(session, subject_user_id)
    return user.email.strip().lower() if user is not None and user.email else None


async def _get_subject_invite_ids(
    session: AsyncSession, subject_user_id: UUID
) -> tuple[UUID, ...]:
    subject_email = await _get_subject_email(session, subject_user_id)
    if subject_email is None:
        return ()

    stmt = (
        select(Invite.id)
        .where(func.lower(Invite.email) == subject_email)
        .order_by(Invite.created_at.asc())
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _get_subject_membership_ids(
    session: AsyncSession, subject_user_id: UUID
) -> tuple[UUID, ...]:
    stmt = select(Membership.id).where(Membership.user_id == subject_user_id)
    return tuple((await session.execute(stmt)).scalars().all())


async def _get_subject_dsr_ids(
    session: AsyncSession, subject_user_id: UUID
) -> tuple[UUID, ...]:
    stmt = select(DataSubjectRequest.id).where(
        or_(
            DataSubjectRequest.subject_user_id == subject_user_id,
            DataSubjectRequest.requester_user_id == subject_user_id,
        )
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _get_subject_export_artifact_ids(
    session: AsyncSession, subject_user_id: UUID
) -> tuple[UUID, ...]:
    stmt = select(ExportArtifact.id).where(
        and_(
            ExportArtifact.status == ExportArtifactStatus.READY.value,
            or_(
                ExportArtifact.subject_user_id == subject_user_id,
                ExportArtifact.requester_user_id == subject_user_id,
            ),
        )
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _get_subject_platform_staff_ids(
    session: AsyncSession, subject_user_id: UUID
) -> tuple[UUID, ...]:
    stmt = select(PlatformStaff.id).where(PlatformStaff.user_id == subject_user_id)
    return tuple((await session.execute(stmt)).scalars().all())


async def _audit_subject_conditions(
    session: AsyncSession, subject_user_id: UUID
) -> list[object]:
    conditions: list[object] = [
        AuditEvent.actor_user_id == subject_user_id,
        and_(
            AuditEvent.target_type == AuditTargetType.USER.value,
            AuditEvent.target_id == subject_user_id,
        ),
        and_(
            AuditEvent.target_type.in_(
                {
                    AuditTargetType.PRIVACY_CONSENT.value,
                    AuditTargetType.PRIVACY_NOTICE.value,
                }
            ),
            AuditEvent.target_id == subject_user_id,
        ),
    ]

    target_sets = (
        (
            AuditTargetType.INVITE.value,
            await _get_subject_invite_ids(session, subject_user_id),
        ),
        (
            AuditTargetType.MEMBERSHIP.value,
            await _get_subject_membership_ids(session, subject_user_id),
        ),
        (
            AuditTargetType.DATA_SUBJECT_REQUEST.value,
            await _get_subject_dsr_ids(session, subject_user_id),
        ),
        (
            AuditTargetType.EXPORT_ARTIFACT.value,
            await _get_subject_export_artifact_ids(session, subject_user_id),
        ),
        (
            AuditTargetType.PLATFORM_STAFF.value,
            await _get_subject_platform_staff_ids(session, subject_user_id),
        ),
    )
    for target_type, target_ids in target_sets:
        if target_ids:
            conditions.append(
                and_(
                    AuditEvent.target_type == target_type,
                    AuditEvent.target_id.in_(target_ids),
                )
            )
    return conditions


def _serialise_record(record: PrivacyExportRecord) -> dict[str, object]:
    return {
        "record_kind": record.record_kind.value,
        "table_name": record.table_name,
        "payload": _json_value(record.payload),
        "redacted_fields": list(record.redacted_fields),
    }


def _include_or_minimise_actor_field(
    payload: dict[str, object],
    redacted_fields: list[str],
    *,
    field_name: str,
    actor_user_id: UUID | None,
    subject_user_id: UUID,
    presence_field: str,
) -> None:
    if actor_user_id is None:
        return
    if actor_user_id == subject_user_id:
        payload[field_name] = actor_user_id
        return
    payload[presence_field] = True
    redacted_fields.append(field_name)


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        normalised = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return normalised.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, str | bytes):
        return [_json_value(item) for item in value]
    return value


def _outbox_payload_reference(
    payload: Mapping[str, object] | None,
) -> tuple[dict[str, object], tuple[str, ...]]:
    if not payload:
        return {}, ()

    exported_keys = {"invite_id", "organisation_id", "purpose", "role"}
    redacted_keys = {"email", "encrypted_raw_token"}
    exported = {
        key: _json_value(value)
        for key, value in payload.items()
        if key in exported_keys
    }
    redacted = tuple(
        f"payload_json.{key}" for key in sorted(redacted_keys.intersection(payload))
    )
    return exported, redacted


_SAFE_AUDIT_METADATA_KEYS = frozenset(
    {
        "organisation_id",
        "invite_role",
        "invite_status_before",
        "request_type",
        "status",
        "format",
    }
)


def _safe_audit_metadata(
    metadata: Mapping[str, object] | None,
) -> tuple[dict[str, object], list[str]]:
    if not metadata:
        return {}, []
    safe = {
        key: _json_value(value)
        for key, value in metadata.items()
        if key in _SAFE_AUDIT_METADATA_KEYS
    }
    redacted = [
        f"metadata_json.{key}"
        for key in sorted(set(metadata) - _SAFE_AUDIT_METADATA_KEYS)
    ]
    return safe, redacted


def _purpose_payload(purpose: ProcessingPurpose) -> dict[str, object]:
    return {
        "id": str(purpose.id),
        "code": purpose.code,
        "title": purpose.title,
        "family": purpose.family,
        "default_lawful_basis": purpose.default_lawful_basis,
        "is_special_category": purpose.is_special_category,
        "default_special_category_condition": (
            purpose.default_special_category_condition
        ),
        "requires_active_consent": purpose.requires_active_consent,
        "active": purpose.active,
    }
