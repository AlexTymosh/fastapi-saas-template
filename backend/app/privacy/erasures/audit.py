from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditEvent, AuditTargetType
from app.invites.models.invite import Invite
from app.memberships.models.membership import Membership
from app.platform.models.platform_staff import PlatformStaff
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import ExportArtifact
from app.users.models.user import User

_PROVIDER_KEY = "audit.minimise_subject_actor_or_target_identifiers"
_TABLE_NAME = "audit_events"
_DIRECT_SUBJECT_TARGET_TYPES = frozenset(
    {
        AuditTargetType.USER.value,
        AuditTargetType.PRIVACY_CONSENT.value,
        AuditTargetType.PRIVACY_NOTICE.value,
    }
)


class AuditErasureStatus(StrEnum):
    MINIMISED = "minimised"
    ALREADY_MINIMISED = "already_minimised"


class AuditErasureError(ValueError):
    """Raised when audit minimisation cannot be applied safely."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class AuditErasureResult:
    provider_key: str
    table_name: str
    subject_user_id: UUID
    status: AuditErasureStatus
    affected_rows: int
    changed_fields: tuple[str, ...]
    minimised_at: datetime

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0


@dataclass(frozen=True, slots=True)
class _AuditTargetSnapshot:
    subject_user_id: UUID
    subject_email: str | None
    invite_ids: tuple[UUID, ...]
    membership_ids: tuple[UUID, ...]
    data_subject_request_ids: tuple[UUID, ...]
    export_artifact_ids: tuple[UUID, ...]
    platform_staff_ids: tuple[UUID, ...]


async def minimise_audit_events_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    now: datetime | None = None,
) -> AuditErasureResult:
    """Minimise subject-linked audit rows for an approved erase DSR.

    Audit rows are retained for integrity. This provider removes direct subject
    identifiers and free-form context from rows where the subject is the actor,
    a direct user/privacy target, or a linked target reached through privacy
    inventory joins. It does not commit and is not wired into the core erasure
    orchestrator yet.
    """

    subject = await _validate_request_and_lock_subject(session, request)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    snapshot = await _build_target_snapshot(session, subject=subject)
    audit_events = await _lock_subject_audit_events(session, snapshot=snapshot)
    _reject_active_legal_hold(audit_events, now=reference_now)

    changed_fields: list[str] = []
    affected_rows = 0
    for audit_event in audit_events:
        row_changes = _minimise_audit_event(
            audit_event,
            snapshot=snapshot,
        )
        if row_changes:
            affected_rows += 1
            _extend_unique(changed_fields, row_changes)

    if affected_rows:
        await session.flush()

    return AuditErasureResult(
        provider_key=_PROVIDER_KEY,
        table_name=_TABLE_NAME,
        subject_user_id=subject.id,
        status=(
            AuditErasureStatus.MINIMISED
            if affected_rows
            else AuditErasureStatus.ALREADY_MINIMISED
        ),
        affected_rows=affected_rows,
        changed_fields=tuple(changed_fields),
        minimised_at=reference_now,
    )


async def _validate_request_and_lock_subject(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> User:
    if request.request_type != DataSubjectRequestType.ERASE.value:
        raise AuditErasureError("audit_erasure_requires_erase_request")
    if request.status != DataSubjectRequestStatus.APPROVED.value:
        raise AuditErasureError("audit_erasure_requires_approved_request")
    if request.subject_user_id is None:
        raise AuditErasureError("audit_erasure_requires_subject_user")

    stmt = (
        select(User)
        .where(User.id == request.subject_user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    subject = (await session.execute(stmt)).scalar_one_or_none()
    if subject is None:
        raise AuditErasureError("audit_erasure_subject_not_found")
    return subject


async def _build_target_snapshot(
    session: AsyncSession,
    *,
    subject: User,
) -> _AuditTargetSnapshot:
    subject_email = _normalise_optional_email(subject.email)
    return _AuditTargetSnapshot(
        subject_user_id=subject.id,
        subject_email=subject_email,
        invite_ids=await _subject_invite_ids(session, subject_email=subject_email),
        membership_ids=await _subject_membership_ids(
            session,
            subject_user_id=subject.id,
        ),
        data_subject_request_ids=await _subject_dsr_ids(
            session,
            subject_user_id=subject.id,
        ),
        export_artifact_ids=await _subject_export_artifact_ids(
            session,
            subject_user_id=subject.id,
        ),
        platform_staff_ids=await _subject_platform_staff_ids(
            session,
            subject_user_id=subject.id,
        ),
    )


async def _subject_invite_ids(
    session: AsyncSession,
    *,
    subject_email: str | None,
) -> tuple[UUID, ...]:
    if subject_email is None:
        return ()
    stmt = select(Invite.id).where(func.lower(func.trim(Invite.email)) == subject_email)
    return tuple((await session.execute(stmt)).scalars().all())


async def _subject_membership_ids(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[UUID, ...]:
    stmt = select(Membership.id).where(Membership.user_id == subject_user_id)
    return tuple((await session.execute(stmt)).scalars().all())


async def _subject_dsr_ids(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[UUID, ...]:
    stmt = select(DataSubjectRequest.id).where(
        or_(
            DataSubjectRequest.subject_user_id == subject_user_id,
            DataSubjectRequest.requester_user_id == subject_user_id,
            DataSubjectRequest.reviewer_user_id == subject_user_id,
        )
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _subject_export_artifact_ids(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[UUID, ...]:
    stmt = select(ExportArtifact.id).where(
        or_(
            ExportArtifact.subject_user_id == subject_user_id,
            ExportArtifact.requester_user_id == subject_user_id,
            ExportArtifact.requested_by_user_id == subject_user_id,
            ExportArtifact.generated_by_user_id == subject_user_id,
        )
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _subject_platform_staff_ids(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[UUID, ...]:
    stmt = select(PlatformStaff.id).where(
        or_(
            PlatformStaff.user_id == subject_user_id,
            PlatformStaff.created_by_user_id == subject_user_id,
        )
    )
    return tuple((await session.execute(stmt)).scalars().all())


async def _lock_subject_audit_events(
    session: AsyncSession,
    *,
    snapshot: _AuditTargetSnapshot,
) -> tuple[AuditEvent, ...]:
    conditions = _subject_audit_conditions(snapshot)
    stmt = (
        select(AuditEvent)
        .where(or_(*conditions))
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _subject_audit_conditions(snapshot: _AuditTargetSnapshot) -> tuple[object, ...]:
    conditions: list[object] = [
        AuditEvent.actor_user_id == snapshot.subject_user_id,
        and_(
            AuditEvent.target_type.in_(_DIRECT_SUBJECT_TARGET_TYPES),
            AuditEvent.target_id == snapshot.subject_user_id,
        ),
    ]
    _append_target_condition(
        conditions,
        target_type=AuditTargetType.INVITE.value,
        target_ids=snapshot.invite_ids,
    )
    _append_target_condition(
        conditions,
        target_type=AuditTargetType.MEMBERSHIP.value,
        target_ids=snapshot.membership_ids,
    )
    _append_target_condition(
        conditions,
        target_type=AuditTargetType.DATA_SUBJECT_REQUEST.value,
        target_ids=snapshot.data_subject_request_ids,
    )
    _append_target_condition(
        conditions,
        target_type=AuditTargetType.EXPORT_ARTIFACT.value,
        target_ids=snapshot.export_artifact_ids,
    )
    _append_target_condition(
        conditions,
        target_type=AuditTargetType.PLATFORM_STAFF.value,
        target_ids=snapshot.platform_staff_ids,
    )
    return tuple(conditions)


def _append_target_condition(
    conditions: list[object],
    *,
    target_type: str,
    target_ids: tuple[UUID, ...],
) -> None:
    if not target_ids:
        return
    conditions.append(
        and_(
            AuditEvent.target_type == target_type,
            AuditEvent.target_id.in_(target_ids),
        )
    )


def _reject_active_legal_hold(
    audit_events: tuple[AuditEvent, ...],
    *,
    now: datetime,
) -> None:
    for audit_event in audit_events:
        legal_hold_until = audit_event.legal_hold_until
        if legal_hold_until is None:
            continue
        if _normalise_reference_time(legal_hold_until) > now:
            raise AuditErasureError("audit_erasure_legal_hold_active")


def _minimise_audit_event(
    audit_event: AuditEvent,
    *,
    snapshot: _AuditTargetSnapshot,
) -> tuple[str, ...]:
    changed_fields: list[str] = []

    if audit_event.actor_user_id == snapshot.subject_user_id:
        _set_if_changed(audit_event, "actor_user_id", None, changed_fields)

    if _is_subject_target(audit_event, snapshot=snapshot):
        _set_if_changed(audit_event, "target_id", None, changed_fields)

    _set_if_changed(audit_event, "reason", None, changed_fields)
    _set_if_changed(audit_event, "metadata_json", None, changed_fields)
    _set_if_changed(audit_event, "ip_address", None, changed_fields)
    _set_if_changed(audit_event, "user_agent", None, changed_fields)
    return tuple(changed_fields)


def _is_subject_target(
    audit_event: AuditEvent,
    *,
    snapshot: _AuditTargetSnapshot,
) -> bool:
    target_type = audit_event.target_type
    target_id = audit_event.target_id
    if target_id is None:
        return False
    if target_type in _DIRECT_SUBJECT_TARGET_TYPES:
        return target_id == snapshot.subject_user_id
    target_sets = {
        AuditTargetType.INVITE.value: snapshot.invite_ids,
        AuditTargetType.MEMBERSHIP.value: snapshot.membership_ids,
        AuditTargetType.DATA_SUBJECT_REQUEST.value: snapshot.data_subject_request_ids,
        AuditTargetType.EXPORT_ARTIFACT.value: snapshot.export_artifact_ids,
        AuditTargetType.PLATFORM_STAFF.value: snapshot.platform_staff_ids,
    }
    return target_id in target_sets.get(target_type, ())


def _set_if_changed(
    audit_event: AuditEvent,
    field_name: str,
    target_value: object,
    changed_fields: list[str],
) -> None:
    if getattr(audit_event, field_name) == target_value:
        return
    setattr(audit_event, field_name, target_value)
    changed_fields.append(field_name)


def _extend_unique(target: list[str], source: tuple[str, ...]) -> None:
    for item in source:
        if item not in target:
            target.append(item)


def _normalise_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip().lower()
    return normalised or None


def _normalise_reference_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
