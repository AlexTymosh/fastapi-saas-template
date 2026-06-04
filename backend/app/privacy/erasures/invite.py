from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.invites.anonymisation import (
    is_scrubbed_invite,
    scrubbed_invite_email,
    scrubbed_invite_token_hash,
)
from app.invites.models.invite import Invite, InviteStatus
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.users.models.user import User

_PROVIDER_KEY = "invites.anonymise_or_purge_subject_references"
_TABLE_NAME = "invites"


class InviteErasureStatus(StrEnum):
    ANONYMISED = "anonymised"
    ALREADY_ANONYMISED = "already_anonymised"


class InviteErasureError(ValueError):
    """Raised when invite erasure cannot be applied safely."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class InviteErasureResult:
    provider_key: str
    table_name: str
    subject_user_id: UUID
    status: InviteErasureStatus
    affected_rows: int
    changed_fields: tuple[str, ...]
    anonymised_at: datetime

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0


async def anonymise_invites_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_email: str | None = None,
    now: datetime | None = None,
) -> InviteErasureResult:
    """Anonymise invite rows linked to an approved erase DSR subject.

    The provider keeps invite rows in place to preserve tenant/audit references.
    Subject invitee rows have email and token material replaced with deterministic
    tombstones. Revoker-only rows keep the invitee data and only remove the
    subject-side revoker link.

    The function does not commit and is not wired into public execution yet.
    """

    subject = await _validate_request_and_get_subject(session, request)
    normalised_email = _normalise_optional_email(subject_email)
    if normalised_email is None:
        normalised_email = _normalise_optional_email(subject.email)

    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    invites = await _lock_subject_invites(
        session,
        subject_user_id=subject.id,
        subject_email=normalised_email,
    )
    changed_fields: list[str] = []
    affected_rows = 0

    for invite in invites:
        row_changes = _anonymise_invite(
            invite,
            subject_user_id=subject.id,
            subject_email=normalised_email,
            now=reference_now,
        )
        if row_changes:
            affected_rows += 1
            _extend_unique(changed_fields, row_changes)

    if affected_rows:
        await session.flush()

    return InviteErasureResult(
        provider_key=_PROVIDER_KEY,
        table_name=_TABLE_NAME,
        subject_user_id=subject.id,
        status=(
            InviteErasureStatus.ANONYMISED
            if affected_rows
            else InviteErasureStatus.ALREADY_ANONYMISED
        ),
        affected_rows=affected_rows,
        changed_fields=tuple(changed_fields),
        anonymised_at=reference_now,
    )


async def _validate_request_and_get_subject(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> User:
    if request.request_type != DataSubjectRequestType.ERASE.value:
        raise InviteErasureError("invite_erasure_requires_erase_request")
    if request.status != DataSubjectRequestStatus.APPROVED.value:
        raise InviteErasureError("invite_erasure_requires_approved_request")
    if request.subject_user_id is None:
        raise InviteErasureError("invite_erasure_requires_subject_user")

    subject = await session.get(User, request.subject_user_id)
    if subject is None:
        raise InviteErasureError("invite_erasure_subject_not_found")
    return subject


async def _lock_subject_invites(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
    subject_email: str | None,
) -> tuple[Invite, ...]:
    conditions: list[object] = [Invite.revoked_by_user_id == subject_user_id]
    if subject_email is not None:
        conditions.append(func.lower(func.trim(Invite.email)) == subject_email)

    stmt = (
        select(Invite)
        .where(or_(*conditions))
        .order_by(Invite.created_at.asc(), Invite.id.asc())
        .with_for_update()
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _anonymise_invite(
    invite: Invite,
    *,
    subject_user_id: UUID,
    subject_email: str | None,
    now: datetime,
) -> tuple[str, ...]:
    changed_fields: list[str] = []
    subject_is_invitee = _invite_email_matches_subject(invite, subject_email)

    if subject_is_invitee and not is_scrubbed_invite(invite):
        _set_if_changed(
            invite,
            "email",
            scrubbed_invite_email(invite.id),
            changed_fields,
        )
        _set_if_changed(
            invite,
            "token_hash",
            scrubbed_invite_token_hash(invite.id),
            changed_fields,
        )
        _set_if_changed(invite, "expires_at", None, changed_fields)
        if _status_value(invite.status) == InviteStatus.PENDING.value:
            _set_if_changed(invite, "status", InviteStatus.REVOKED, changed_fields)
            _set_if_changed(invite, "revoked_at", now, changed_fields)

    if invite.revoked_by_user_id == subject_user_id:
        _set_if_changed(invite, "revoked_by_user_id", None, changed_fields)

    return tuple(changed_fields)


def _invite_email_matches_subject(
    invite: Invite,
    subject_email: str | None,
) -> bool:
    if subject_email is None:
        return False
    return invite.email.strip().lower() == subject_email


def _set_if_changed(
    invite: Invite,
    field_name: str,
    target_value: object,
    changed_fields: list[str],
) -> None:
    if getattr(invite, field_name) == target_value:
        return
    setattr(invite, field_name, target_value)
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


def _status_value(value: object) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)
