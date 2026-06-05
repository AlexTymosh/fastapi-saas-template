from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditEvent, AuditTargetType
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
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


async def minimise_audit_events_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    now: datetime | None = None,
) -> AuditErasureResult:
    """Minimise direct subject-linked audit rows for an approved erase DSR.

    Audit rows are retained for integrity. This provider removes direct subject
    identifiers and free-form context from rows where the subject is the actor or
    a direct user/privacy target. It does not commit and is not wired into the
    core erasure orchestrator yet.
    """

    subject = await _validate_request_and_lock_subject(session, request)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    audit_events = await _lock_direct_subject_audit_events(
        session,
        subject_user_id=subject.id,
    )
    _reject_active_legal_hold(audit_events, now=reference_now)

    changed_fields: list[str] = []
    affected_rows = 0
    for audit_event in audit_events:
        row_changes = _minimise_audit_event(
            audit_event,
            subject_user_id=subject.id,
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


async def _lock_direct_subject_audit_events(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
) -> tuple[AuditEvent, ...]:
    stmt = (
        select(AuditEvent)
        .where(
            or_(
                AuditEvent.actor_user_id == subject_user_id,
                and_(
                    AuditEvent.target_type.in_(_DIRECT_SUBJECT_TARGET_TYPES),
                    AuditEvent.target_id == subject_user_id,
                ),
            )
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


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
    subject_user_id: UUID,
) -> tuple[str, ...]:
    changed_fields: list[str] = []

    if audit_event.actor_user_id == subject_user_id:
        _set_if_changed(audit_event, "actor_user_id", None, changed_fields)

    if _is_direct_subject_target(audit_event, subject_user_id=subject_user_id):
        _set_if_changed(audit_event, "target_id", None, changed_fields)

    _set_if_changed(audit_event, "reason", None, changed_fields)
    _set_if_changed(audit_event, "metadata_json", None, changed_fields)
    _set_if_changed(audit_event, "ip_address", None, changed_fields)
    _set_if_changed(audit_event, "user_agent", None, changed_fields)
    return tuple(changed_fields)


def _is_direct_subject_target(
    audit_event: AuditEvent,
    *,
    subject_user_id: UUID,
) -> bool:
    return (
        audit_event.target_type in _DIRECT_SUBJECT_TARGET_TYPES
        and audit_event.target_id == subject_user_id
    )


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


def _normalise_reference_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
