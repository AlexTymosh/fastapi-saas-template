from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditEvent, AuditTargetType
from app.invites.models.invite import Invite
from app.memberships.models.membership import Membership
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent
from app.platform.models.platform_staff import PlatformStaff
from app.privacy.erasures.coverage import inventory_erasure_provider_keys
from app.privacy.erasures.plan import ErasureExecutionMode
from app.privacy.erasures.preview import (
    ErasurePreviewEntry,
    ErasurePreviewReadiness,
    build_erasure_preview,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import ExportArtifact
from app.privacy.models.privacy_governance import (
    ConsentRecord,
    DataProcessingAuthorization,
    PrivacyNoticeAcceptance,
)
from app.users.models.user import User

_USERS_PROVIDER_KEY = "users.anonymise_profile"
_INVITES_PROVIDER_KEY = "invites.anonymise_or_purge_subject_references"
_OUTBOX_PROVIDER_KEY = "outbox.purge_or_scrub_payload"
_AUDIT_PROVIDER_KEY = "audit.minimise_subject_actor_or_target_identifiers"
_MEMBERSHIPS_PROVIDER_KEY = "memberships.minimise_subject_link"
_ORGANISATIONS_PROVIDER_KEY = "organisations.review_subject_references"
_PLATFORM_STAFF_PROVIDER_KEY = "platform_staff.minimise_subject_or_creator_links"
_DSR_PROVIDER_KEY = "dsr.minimise_workflow_identifiers"
_EXPORT_ARTIFACTS_PROVIDER_KEY = (
    "export_artifacts.delete_object_minimise_subject_or_actor_metadata"
)
_PRIVACY_AUTHORIZATIONS_PROVIDER_KEY = "privacy_governance.minimise_authorizations"
_PRIVACY_CONSENTS_PROVIDER_KEY = "privacy_governance.minimise_consent_records"
_PRIVACY_NOTICES_PROVIDER_KEY = "privacy_governance.minimise_notice_acceptances"
_SCOPED_PROVIDER_KEYS = inventory_erasure_provider_keys()


class ErasureImpactScope(StrEnum):
    SCOPED = "scoped"
    NOT_SCOPED_YET = "not_scoped_yet"


class ErasureImpactPreviewError(ValueError):
    """Raised when a DSR is not eligible for erasure impact preview."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ErasureImpactEntry:
    provider_key: str
    table_name: str
    execution_mode: ErasureExecutionMode
    readiness: ErasurePreviewReadiness
    requires_manual_review: bool
    retention_policy_key: str
    impact_scope: ErasureImpactScope
    estimated_rows: int | None

    @property
    def is_scoped(self) -> bool:
        return self.impact_scope is ErasureImpactScope.SCOPED


@dataclass(frozen=True, slots=True)
class ErasureImpactPreview:
    request_id: UUID
    subject_user_id: UUID
    entries: tuple[ErasureImpactEntry, ...]

    @property
    def scoped_provider_keys(self) -> tuple[str, ...]:
        return tuple(entry.provider_key for entry in self.entries if entry.is_scoped)

    @property
    def unscoped_provider_keys(self) -> tuple[str, ...]:
        return tuple(
            entry.provider_key for entry in self.entries if not entry.is_scoped
        )

    @property
    def total_scoped_rows(self) -> int:
        return sum(entry.estimated_rows or 0 for entry in self.entries)


async def build_erasure_impact_preview(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> ErasureImpactPreview:
    """Build a non-destructive, DB-backed erasure impact preview.

    The preview counts every inventory-backed erasure target so platform review
    can see which tables are executable, retained by policy, or require manual
    review before executing the DSR.
    """

    subject = await _validate_request_and_get_subject(session, request)
    base_preview = build_erasure_preview(
        request_id=request.id,
        subject_user_id=subject.id,
        request_type=DataSubjectRequestType.ERASE,
    )
    row_counts = await _count_scoped_rows(session, subject)

    return ErasureImpactPreview(
        request_id=request.id,
        subject_user_id=subject.id,
        entries=tuple(
            _impact_entry(entry, row_counts) for entry in base_preview.entries
        ),
    )


async def _validate_request_and_get_subject(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> User:
    if request.request_type != DataSubjectRequestType.ERASE.value:
        raise ErasureImpactPreviewError("erasure_preview_requires_erase_request")
    if request.status != DataSubjectRequestStatus.APPROVED.value:
        raise ErasureImpactPreviewError("erasure_preview_requires_approved_request")
    if request.subject_user_id is None:
        raise ErasureImpactPreviewError("erasure_preview_requires_subject_user")

    subject = await session.get(User, request.subject_user_id)
    if subject is None:
        raise ErasureImpactPreviewError("erasure_preview_subject_not_found")
    return subject


async def _count_scoped_rows(
    session: AsyncSession,
    subject: User,
) -> dict[str, int]:
    subject_email = _normalised_subject_email(subject)
    invite_ids = await _subject_invite_ids(session, subject, subject_email)
    return {
        _USERS_PROVIDER_KEY: 1,
        _INVITES_PROVIDER_KEY: len(invite_ids),
        _OUTBOX_PROVIDER_KEY: await _count_subject_outbox_events(
            session,
            invite_ids,
            subject_email,
        ),
        _AUDIT_PROVIDER_KEY: await _count_subject_audit_events(
            session,
            subject,
            invite_ids,
        ),
        _MEMBERSHIPS_PROVIDER_KEY: await _count_subject_memberships(session, subject),
        _ORGANISATIONS_PROVIDER_KEY: await _count_subject_organisations(
            session,
            subject,
        ),
        _PLATFORM_STAFF_PROVIDER_KEY: await _count_subject_platform_staff(
            session,
            subject,
        ),
        _DSR_PROVIDER_KEY: await _count_subject_dsr_records(session, subject),
        _EXPORT_ARTIFACTS_PROVIDER_KEY: await _count_subject_export_artifacts(
            session,
            subject,
        ),
        _PRIVACY_AUTHORIZATIONS_PROVIDER_KEY: await _count_subject_authorizations(
            session,
            subject,
        ),
        _PRIVACY_CONSENTS_PROVIDER_KEY: await _count_subject_consents(
            session,
            subject,
        ),
        _PRIVACY_NOTICES_PROVIDER_KEY: await _count_subject_notice_acceptances(
            session,
            subject,
        ),
    }


async def _subject_invite_ids(
    session: AsyncSession,
    subject: User,
    subject_email: str | None,
) -> tuple[UUID, ...]:
    conditions = _subject_invite_conditions(subject, subject_email)
    stmt = select(Invite.id).where(or_(*conditions)).order_by(Invite.id.asc())
    result = await session.execute(stmt)
    return tuple(result.scalars().all())


def _subject_invite_conditions(
    subject: User,
    subject_email: str | None,
) -> list[object]:
    conditions: list[object] = [Invite.revoked_by_user_id == subject.id]
    if subject_email is not None:
        conditions.append(func.lower(func.trim(Invite.email)) == subject_email)
    return conditions


async def _count_subject_outbox_events(
    session: AsyncSession,
    invite_ids: tuple[UUID, ...],
    subject_email: str | None,
) -> int:
    conditions = []
    if invite_ids:
        conditions.append(OutboxEvent.aggregate_id.in_(invite_ids))
    if subject_email is not None:
        payload_email = OutboxEvent.payload_json["email"].as_string()
        conditions.append(func.lower(func.trim(payload_email)) == subject_email)
    if not conditions:
        return 0

    stmt = select(func.count(distinct(OutboxEvent.id))).where(or_(*conditions))
    return int(await session.scalar(stmt) or 0)


async def _count_subject_audit_events(
    session: AsyncSession,
    subject: User,
    invite_ids: tuple[UUID, ...],
) -> int:
    membership_ids = await _subject_membership_ids(session, subject)
    dsr_ids = await _subject_dsr_ids(session, subject)
    export_artifact_ids = await _subject_export_artifact_ids(session, subject)
    platform_staff_ids = await _subject_platform_staff_ids(session, subject)
    conditions: list[object] = [
        AuditEvent.actor_user_id == subject.id,
        (
            AuditEvent.target_type.in_(
                {
                    AuditTargetType.USER.value,
                    AuditTargetType.PRIVACY_CONSENT.value,
                    AuditTargetType.PRIVACY_NOTICE.value,
                }
            )
            & (AuditEvent.target_id == subject.id)
        ),
    ]
    _append_audit_target_condition(
        conditions,
        target_type=AuditTargetType.INVITE.value,
        target_ids=invite_ids,
    )
    _append_audit_target_condition(
        conditions,
        target_type=AuditTargetType.MEMBERSHIP.value,
        target_ids=membership_ids,
    )
    _append_audit_target_condition(
        conditions,
        target_type=AuditTargetType.DATA_SUBJECT_REQUEST.value,
        target_ids=dsr_ids,
    )
    _append_audit_target_condition(
        conditions,
        target_type=AuditTargetType.EXPORT_ARTIFACT.value,
        target_ids=export_artifact_ids,
    )
    _append_audit_target_condition(
        conditions,
        target_type=AuditTargetType.PLATFORM_STAFF.value,
        target_ids=platform_staff_ids,
    )
    stmt = select(func.count(distinct(AuditEvent.id))).where(or_(*conditions))
    return int(await session.scalar(stmt) or 0)


def _append_audit_target_condition(
    conditions: list[object],
    *,
    target_type: str,
    target_ids: tuple[UUID, ...],
) -> None:
    if not target_ids:
        return
    conditions.append(
        (AuditEvent.target_type == target_type) & (AuditEvent.target_id.in_(target_ids))
    )


async def _subject_membership_ids(
    session: AsyncSession,
    subject: User,
) -> tuple[UUID, ...]:
    stmt = select(Membership.id).where(Membership.user_id == subject.id)
    return tuple((await session.execute(stmt)).scalars().all())


async def _subject_dsr_ids(
    session: AsyncSession,
    subject: User,
) -> tuple[UUID, ...]:
    stmt = select(DataSubjectRequest.id).where(or_(*_subject_dsr_conditions(subject)))
    return tuple((await session.execute(stmt)).scalars().all())


def _subject_dsr_conditions(subject: User) -> tuple[object, ...]:
    return (
        DataSubjectRequest.subject_user_id == subject.id,
        DataSubjectRequest.requester_user_id == subject.id,
        DataSubjectRequest.reviewer_user_id == subject.id,
        DataSubjectRequest.representative_verified_by_user_id == subject.id,
    )


async def _subject_export_artifact_ids(
    session: AsyncSession,
    subject: User,
) -> tuple[UUID, ...]:
    stmt = select(ExportArtifact.id).where(
        or_(
            ExportArtifact.subject_user_id == subject.id,
            ExportArtifact.requester_user_id == subject.id,
            ExportArtifact.requested_by_user_id == subject.id,
            ExportArtifact.generated_by_user_id == subject.id,
        )
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _subject_platform_staff_ids(
    session: AsyncSession,
    subject: User,
) -> tuple[UUID, ...]:
    stmt = select(PlatformStaff.id).where(
        or_(
            PlatformStaff.user_id == subject.id,
            PlatformStaff.created_by_user_id == subject.id,
        )
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _count_subject_memberships(session: AsyncSession, subject: User) -> int:
    stmt = (
        select(func.count())
        .select_from(Membership)
        .where(Membership.user_id == subject.id)
    )
    return int(await session.scalar(stmt) or 0)


async def _count_subject_organisations(session: AsyncSession, subject: User) -> int:
    stmt = (
        select(func.count(distinct(Organisation.id)))
        .select_from(Organisation)
        .join(Membership, Membership.organisation_id == Organisation.id)
        .where(Membership.user_id == subject.id)
    )
    return int(await session.scalar(stmt) or 0)


async def _count_subject_platform_staff(session: AsyncSession, subject: User) -> int:
    stmt = (
        select(func.count())
        .select_from(PlatformStaff)
        .where(
            or_(
                PlatformStaff.user_id == subject.id,
                PlatformStaff.created_by_user_id == subject.id,
            )
        )
    )
    return int(await session.scalar(stmt) or 0)


async def _count_subject_dsr_records(session: AsyncSession, subject: User) -> int:
    stmt = (
        select(func.count())
        .select_from(DataSubjectRequest)
        .where(or_(*_subject_dsr_conditions(subject)))
    )
    return int(await session.scalar(stmt) or 0)


async def _count_subject_export_artifacts(session: AsyncSession, subject: User) -> int:
    stmt = (
        select(func.count())
        .select_from(ExportArtifact)
        .where(
            or_(
                ExportArtifact.subject_user_id == subject.id,
                ExportArtifact.requester_user_id == subject.id,
                ExportArtifact.requested_by_user_id == subject.id,
                ExportArtifact.generated_by_user_id == subject.id,
            )
        )
    )
    return int(await session.scalar(stmt) or 0)


async def _count_subject_authorizations(session: AsyncSession, subject: User) -> int:
    stmt = (
        select(func.count())
        .select_from(DataProcessingAuthorization)
        .where(DataProcessingAuthorization.subject_user_id == subject.id)
    )
    return int(await session.scalar(stmt) or 0)


async def _count_subject_consents(session: AsyncSession, subject: User) -> int:
    stmt = (
        select(func.count())
        .select_from(ConsentRecord)
        .where(ConsentRecord.subject_user_id == subject.id)
    )
    return int(await session.scalar(stmt) or 0)


async def _count_subject_notice_acceptances(
    session: AsyncSession,
    subject: User,
) -> int:
    stmt = (
        select(func.count())
        .select_from(PrivacyNoticeAcceptance)
        .where(PrivacyNoticeAcceptance.subject_user_id == subject.id)
    )
    return int(await session.scalar(stmt) or 0)


def _normalised_subject_email(subject: User) -> str | None:
    if subject.email is None:
        return None
    normalised = subject.email.strip().lower()
    return normalised or None


def _impact_entry(
    entry: ErasurePreviewEntry,
    row_counts: dict[str, int],
) -> ErasureImpactEntry:
    is_scoped = entry.provider_key in _SCOPED_PROVIDER_KEYS
    return ErasureImpactEntry(
        provider_key=entry.provider_key,
        table_name=entry.table_name,
        execution_mode=entry.execution_mode,
        readiness=entry.readiness,
        requires_manual_review=entry.requires_manual_review,
        retention_policy_key=entry.retention_policy_key,
        impact_scope=(
            ErasureImpactScope.SCOPED
            if is_scoped
            else ErasureImpactScope.NOT_SCOPED_YET
        ),
        estimated_rows=row_counts.get(entry.provider_key) if is_scoped else None,
    )
