from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.invites.models.invite import Invite
from app.outbox.models.outbox_event import OutboxEvent
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
from app.users.models.user import User

_USERS_PROVIDER_KEY = "users.anonymise_profile"
_INVITES_PROVIDER_KEY = "invites.anonymise_or_purge_subject_references"
_OUTBOX_PROVIDER_KEY = "outbox.purge_or_scrub_payload"
_SCOPED_PROVIDER_KEYS = frozenset(
    {
        _USERS_PROVIDER_KEY,
        _INVITES_PROVIDER_KEY,
        _OUTBOX_PROVIDER_KEY,
    }
)


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

    This function intentionally counts rows only. It does not update, delete or
    anonymise data. The first scoped slice covers user profile, invite and outbox
    providers; later branches should add audit and retention-aware providers.
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
            subject,
            invite_ids,
            subject_email,
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
    subject: User,
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
