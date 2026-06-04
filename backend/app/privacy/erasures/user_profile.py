from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.users.models.user import User

_PROVIDER_KEY = "users.anonymise_profile"
_TABLE_NAME = "users"
_ERASED_EXTERNAL_AUTH_PREFIX = "erased-user"


class UserProfileErasureStatus(StrEnum):
    ANONYMISED = "anonymised"
    ALREADY_ANONYMISED = "already_anonymised"


class UserProfileErasureError(ValueError):
    """Raised when a user profile cannot be anonymised safely."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class UserProfileErasureResult:
    provider_key: str
    table_name: str
    subject_user_id: UUID
    status: UserProfileErasureStatus
    affected_rows: int
    changed_fields: tuple[str, ...]
    anonymised_at: datetime

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0


async def anonymise_user_profile_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    now: datetime | None = None,
) -> UserProfileErasureResult:
    """Anonymise the subject's local user profile for an approved erase DSR.

    The function mutates only the `users` row. It does not commit the
    transaction and does not touch invites, outbox, audit or DSR lifecycle
    fields. Wider erasure orchestration should call this inside an explicit
    transaction and record audit/execution status in a later slice.
    """

    subject = await _validate_request_and_lock_subject(session, request)
    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    changed_fields = _anonymise_subject_profile(subject)
    if not changed_fields:
        return UserProfileErasureResult(
            provider_key=_PROVIDER_KEY,
            table_name=_TABLE_NAME,
            subject_user_id=subject.id,
            status=UserProfileErasureStatus.ALREADY_ANONYMISED,
            affected_rows=0,
            changed_fields=(),
            anonymised_at=reference_now,
        )

    await session.flush()
    return UserProfileErasureResult(
        provider_key=_PROVIDER_KEY,
        table_name=_TABLE_NAME,
        subject_user_id=subject.id,
        status=UserProfileErasureStatus.ANONYMISED,
        affected_rows=1,
        changed_fields=changed_fields,
        anonymised_at=reference_now,
    )


async def _validate_request_and_lock_subject(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> User:
    if request.request_type != DataSubjectRequestType.ERASE.value:
        raise UserProfileErasureError("user_profile_erasure_requires_erase_request")
    if request.status != DataSubjectRequestStatus.APPROVED.value:
        raise UserProfileErasureError("user_profile_erasure_requires_approved_request")
    if request.subject_user_id is None:
        raise UserProfileErasureError("user_profile_erasure_requires_subject_user")

    stmt = select(User).where(User.id == request.subject_user_id).with_for_update()
    subject = (await session.execute(stmt)).scalar_one_or_none()
    if subject is None:
        raise UserProfileErasureError("user_profile_erasure_subject_not_found")
    return subject


def _anonymise_subject_profile(subject: User) -> tuple[str, ...]:
    changed_fields: list[str] = []
    _set_if_changed(
        subject,
        "external_auth_id",
        _erased_external_auth_id(subject.id),
        changed_fields,
    )
    _set_if_changed(subject, "email", None, changed_fields)
    _set_if_changed(subject, "email_verified", False, changed_fields)
    _set_if_changed(subject, "first_name", None, changed_fields)
    _set_if_changed(subject, "last_name", None, changed_fields)
    _set_if_changed(subject, "onboarding_completed", False, changed_fields)
    _set_if_changed(subject, "suspended_reason", None, changed_fields)
    return tuple(changed_fields)


def _set_if_changed(
    subject: User,
    field_name: str,
    target_value: object,
    changed_fields: list[str],
) -> None:
    if getattr(subject, field_name) == target_value:
        return
    setattr(subject, field_name, target_value)
    changed_fields.append(field_name)


def _erased_external_auth_id(subject_user_id: UUID) -> str:
    return f"{_ERASED_EXTERNAL_AUTH_PREFIX}:{subject_user_id}"


def _normalise_reference_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
