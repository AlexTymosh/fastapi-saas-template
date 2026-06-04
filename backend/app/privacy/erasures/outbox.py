from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models.outbox_event import OutboxEvent, OutboxStatus
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.users.models.user import User

_PROVIDER_KEY = "outbox.purge_or_scrub_payload"
_TABLE_NAME = "outbox_events"
_PRIVACY_ERASURE_LAST_ERROR = "privacy_erasure_scrubbed"
_PROCESSING_ROWS_IN_FLIGHT_ERROR = "outbox_erasure_processing_rows_in_flight"
_SAFE_INVITE_PAYLOAD_KEYS = frozenset(
    {
        "invite_id",
        "organisation_id",
        "purpose",
        "role",
    }
)
_SCRUBBED_PAYLOAD_MARKER = "sensitive_payload_scrubbed"
_PRIVACY_ERASURE_MARKER = "privacy_erasure_scrubbed"


class OutboxErasureStatus(StrEnum):
    SCRUBBED = "scrubbed"
    ALREADY_SCRUBBED = "already_scrubbed"


class OutboxErasureError(ValueError):
    """Raised when outbox erasure cannot be applied safely."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class OutboxErasureResult:
    provider_key: str
    table_name: str
    subject_user_id: UUID
    status: OutboxErasureStatus
    affected_rows: int
    changed_fields: tuple[str, ...]
    scrubbed_at: datetime

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0


async def scrub_outbox_for_approved_erase_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    subject_email: str | None = None,
    invite_ids: Iterable[UUID] = (),
    now: datetime | None = None,
) -> OutboxErasureResult:
    """Scrub subject-linked outbox payloads for an approved erase DSR.

    This provider mutates only outbox rows. It does not commit and is not wired
    into public execution yet. Callers should pass pre-erasure subject email and
    invite id snapshots when this provider runs after user/invite anonymisation.

    Processing rows are deliberately rejected. A worker may already have read
    and decrypted delivery material before this provider can lock or update the
    row, so marking such rows as failed here would not reliably cancel delivery.
    """

    subject = await _validate_request_and_get_subject(session, request)
    normalised_email = _normalise_optional_email(subject_email)
    if normalised_email is None:
        normalised_email = _normalise_optional_email(subject.email)

    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    events = await _lock_subject_outbox_events(
        session,
        subject_email=normalised_email,
        invite_ids=_normalise_invite_ids(invite_ids),
    )
    _raise_if_processing_events(events)

    changed_fields: list[str] = []
    affected_rows = 0

    for event in events:
        row_changes = _scrub_outbox_event(event)
        if row_changes:
            affected_rows += 1
            _extend_unique(changed_fields, row_changes)

    if affected_rows:
        await session.flush()

    return OutboxErasureResult(
        provider_key=_PROVIDER_KEY,
        table_name=_TABLE_NAME,
        subject_user_id=subject.id,
        status=(
            OutboxErasureStatus.SCRUBBED
            if affected_rows
            else OutboxErasureStatus.ALREADY_SCRUBBED
        ),
        affected_rows=affected_rows,
        changed_fields=tuple(changed_fields),
        scrubbed_at=reference_now,
    )


async def _validate_request_and_get_subject(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> User:
    if request.request_type != DataSubjectRequestType.ERASE.value:
        raise OutboxErasureError("outbox_erasure_requires_erase_request")
    if request.status != DataSubjectRequestStatus.APPROVED.value:
        raise OutboxErasureError("outbox_erasure_requires_approved_request")
    if request.subject_user_id is None:
        raise OutboxErasureError("outbox_erasure_requires_subject_user")

    subject = await session.get(User, request.subject_user_id)
    if subject is None:
        raise OutboxErasureError("outbox_erasure_subject_not_found")
    return subject


async def _lock_subject_outbox_events(
    session: AsyncSession,
    *,
    subject_email: str | None,
    invite_ids: tuple[UUID, ...],
) -> tuple[OutboxEvent, ...]:
    conditions: list[object] = []
    if invite_ids:
        conditions.append(OutboxEvent.aggregate_id.in_(invite_ids))
    if subject_email is not None:
        payload_email = OutboxEvent.payload_json["email"].as_string()
        conditions.append(func.lower(func.trim(payload_email)) == subject_email)
    if not conditions:
        return ()

    stmt = (
        select(OutboxEvent)
        .where(or_(*conditions))
        .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .with_for_update()
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _raise_if_processing_events(events: tuple[OutboxEvent, ...]) -> None:
    has_processing_event = any(
        _status_value(event.status) == OutboxStatus.PROCESSING.value for event in events
    )
    if has_processing_event:
        raise OutboxErasureError(_PROCESSING_ROWS_IN_FLIGHT_ERROR)


def _scrub_outbox_event(event: OutboxEvent) -> tuple[str, ...]:
    changed_fields: list[str] = []
    scrubbed_payload = _scrubbed_payload(event.payload_json)
    _set_if_changed(event, "payload_json", scrubbed_payload, changed_fields)

    status = _status_value(event.status)
    if status == OutboxStatus.PENDING.value:
        _set_if_changed(event, "status", OutboxStatus.FAILED.value, changed_fields)
        _set_if_changed(event, "locked_at", None, changed_fields)
        _set_if_changed(event, "next_attempt_at", None, changed_fields)
        _set_if_changed(
            event,
            "last_error",
            _PRIVACY_ERASURE_LAST_ERROR,
            changed_fields,
        )
    elif (
        event.last_error is not None and event.last_error != _PRIVACY_ERASURE_LAST_ERROR
    ):
        _set_if_changed(event, "last_error", None, changed_fields)

    return tuple(changed_fields)


def _scrubbed_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        payload = {}

    scrubbed = {
        key: value for key, value in payload.items() if key in _SAFE_INVITE_PAYLOAD_KEYS
    }
    scrubbed[_SCRUBBED_PAYLOAD_MARKER] = True
    scrubbed[_PRIVACY_ERASURE_MARKER] = True
    return scrubbed


def _set_if_changed(
    event: OutboxEvent,
    field_name: str,
    target_value: object,
    changed_fields: list[str],
) -> None:
    if getattr(event, field_name) == target_value:
        return
    setattr(event, field_name, target_value)
    changed_fields.append(field_name)


def _extend_unique(target: list[str], source: tuple[str, ...]) -> None:
    for item in source:
        if item not in target:
            target.append(item)


def _normalise_invite_ids(invite_ids: Iterable[UUID]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(invite_ids))


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
