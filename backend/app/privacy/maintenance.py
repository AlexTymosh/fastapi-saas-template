from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditCategory, AuditEvent
from app.core.config.settings import get_settings
from app.invites.anonymisation import (
    SCRUBBED_INVITE_EMAIL_DOMAIN,
    SCRUBBED_INVITE_TOKEN_PREFIX,
    is_scrubbed_invite,
    scrubbed_invite_email,
    scrubbed_invite_token_hash,
)
from app.invites.models.invite import Invite, InviteStatus
from app.outbox.models.outbox_event import OutboxEvent, OutboxStatus
from app.privacy.models.data_subject_request import DataSubjectRequest
from app.privacy.services.export_artifacts import ExportArtifactService

_OUTBOX_DELIVERY_RETENTION_DAYS = 30
_PRIVACY_RETENTION_LAST_ERROR = "privacy_retention_scrubbed"
_SAFE_OUTBOX_PAYLOAD_KEYS = frozenset(
    {
        "invite_id",
        "organisation_id",
        "purpose",
        "role",
    }
)
_SCRUBBED_PAYLOAD_MARKER = "sensitive_payload_scrubbed"
_PRIVACY_RETENTION_MARKER = "privacy_retention_scrubbed"


@dataclass(frozen=True, slots=True)
class PrivacyRetentionMaintenanceSummary:
    """Per-table mutation preview/result for one privacy retention pass."""

    expired_export_artifacts: int
    anonymised_invites: int
    scrubbed_outbox_events: int
    minimised_audit_events: int
    cleaned_dsr_idempotency_keys: int

    @property
    def total(self) -> int:
        return sum(asdict(self).values())

    def as_log_extra(self) -> dict[str, int]:
        return asdict(self) | {"total": self.total}


async def run_privacy_retention_maintenance(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 1000,
    dry_run: bool = False,
) -> PrivacyRetentionMaintenanceSummary:
    """Run one bounded privacy retention pass across DSR-adjacent data.

    Transaction ownership remains with the caller so this helper can be reused
    by a CLI command, scheduled worker, or explicit maintenance job.

    Dry-run mode performs a non-mutating database/storage preview. Each step is
    capped by ``limit`` so operators can safely run repeated maintenance passes.
    Export artifacts first enter a durable non-downloadable DB state. Storage
    object purge only runs for already non-downloadable retry rows.
    """

    if limit < 1:
        raise ValueError("Privacy retention batch size must be positive")

    reference_now = _normalise_utc(now)
    anonymised_invites = await _anonymise_retained_invites(
        session,
        now=reference_now,
        limit=limit,
        dry_run=dry_run,
    )
    scrubbed_outbox_events = await _scrub_retained_outbox_events(
        session,
        now=reference_now,
        limit=limit,
        dry_run=dry_run,
    )
    minimised_audit_events = await _minimise_retained_audit_events(
        session,
        now=reference_now,
        limit=limit,
        dry_run=dry_run,
    )
    cleaned_dsr_idempotency_keys = await _clean_expired_dsr_idempotency_keys(
        session,
        now=reference_now,
        limit=limit,
        dry_run=dry_run,
    )
    expired_export_artifacts = await expire_ready_export_artifacts(
        session,
        now=reference_now,
        limit=limit,
        dry_run=dry_run,
    )

    return PrivacyRetentionMaintenanceSummary(
        expired_export_artifacts=expired_export_artifacts,
        anonymised_invites=anonymised_invites,
        scrubbed_outbox_events=scrubbed_outbox_events,
        minimised_audit_events=minimised_audit_events,
        cleaned_dsr_idempotency_keys=cleaned_dsr_idempotency_keys,
    )


async def expire_ready_export_artifacts(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 1000,
    dry_run: bool = False,
) -> int:
    """Expire ready exports and purge already non-downloadable objects.

    Transaction ownership remains with the caller so this helper can be reused
    by a CLI command, scheduled worker, or explicit maintenance job.

    Dry-run mode performs a non-mutating database preview and deliberately does
    not touch external storage. Non-dry-run mode does not delete stored objects
    while a rollback could restore an artifact to ``ready``.
    """

    reference_now = _normalise_utc(now)
    service = ExportArtifactService(session)
    if dry_run:
        return await service.count_expired_ready_artifacts(
            now=reference_now,
            limit=limit,
        )
    return await service.mark_expired_artifacts(
        now=reference_now,
        limit=limit,
    )


async def _anonymise_retained_invites(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    dry_run: bool,
) -> int:
    invites = await _load_retained_invites(session, now=now, limit=limit)
    affected_rows = sum(1 for invite in invites if _invite_needs_retention(invite))
    if dry_run or affected_rows == 0:
        return affected_rows

    for invite in invites:
        if _invite_needs_retention(invite):
            _apply_invite_retention(invite)
    await session.flush()
    return affected_rows


async def _load_retained_invites(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> tuple[Invite, ...]:
    settings = get_settings().invite_retention
    accepted_cutoff = now - timedelta(days=settings.accepted_days)
    expired_cutoff = now - timedelta(days=settings.expired_days)
    revoked_cutoff = now - timedelta(days=settings.revoked_days)

    stmt = (
        select(Invite)
        .where(
            or_(
                and_(
                    Invite.status == InviteStatus.ACCEPTED.value,
                    Invite.updated_at <= accepted_cutoff,
                ),
                and_(
                    Invite.status == InviteStatus.EXPIRED.value,
                    func.coalesce(
                        Invite.expires_at,
                        Invite.updated_at,
                        Invite.created_at,
                    )
                    <= expired_cutoff,
                ),
                and_(
                    Invite.status == InviteStatus.REVOKED.value,
                    func.coalesce(
                        Invite.revoked_at,
                        Invite.updated_at,
                        Invite.created_at,
                    )
                    <= revoked_cutoff,
                ),
            ),
            _invite_needs_retention_condition(),
        )
        .order_by(Invite.updated_at.asc(), Invite.id.asc())
        .limit(limit)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _invite_needs_retention_condition() -> object:
    scrubbed_email_pattern = f"%@{SCRUBBED_INVITE_EMAIL_DOMAIN}"
    scrubbed_token_pattern = f"{SCRUBBED_INVITE_TOKEN_PREFIX}:%"
    return or_(
        ~Invite.email.like(scrubbed_email_pattern),
        ~Invite.token_hash.like(scrubbed_token_pattern),
        Invite.revoked_by_user_id.is_not(None),
        Invite.expires_at.is_not(None),
    )


def _invite_needs_retention(invite: Invite) -> bool:
    return (
        not is_scrubbed_invite(invite)
        or invite.revoked_by_user_id is not None
        or invite.expires_at is not None
    )


def _apply_invite_retention(invite: Invite) -> None:
    invite.email = scrubbed_invite_email(invite.id)
    invite.token_hash = scrubbed_invite_token_hash(invite.id)
    invite.expires_at = None
    invite.revoked_by_user_id = None


async def _scrub_retained_outbox_events(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    dry_run: bool,
) -> int:
    events = await _load_retained_outbox_events(session, now=now, limit=limit)
    affected_rows = sum(1 for event in events if _outbox_event_needs_retention(event))
    if dry_run or affected_rows == 0:
        return affected_rows

    for event in events:
        if _outbox_event_needs_retention(event):
            _apply_outbox_retention(event)
    await session.flush()
    return affected_rows


async def _load_retained_outbox_events(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> tuple[OutboxEvent, ...]:
    cutoff = now - timedelta(days=_OUTBOX_DELIVERY_RETENTION_DAYS)
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.status.in_(
                (OutboxStatus.PROCESSED.value, OutboxStatus.FAILED.value)
            ),
            func.coalesce(
                OutboxEvent.processed_at,
                OutboxEvent.updated_at,
                OutboxEvent.created_at,
            )
            <= cutoff,
            _outbox_event_needs_retention_condition(),
        )
        .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .limit(limit)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _outbox_event_needs_retention_condition() -> object:
    payload_marker = OutboxEvent.payload_json[_PRIVACY_RETENTION_MARKER].as_boolean()
    failed_with_free_text = and_(
        OutboxEvent.status == OutboxStatus.FAILED.value,
        OutboxEvent.last_error.is_not(None),
        OutboxEvent.last_error != _PRIVACY_RETENTION_LAST_ERROR,
    )
    stale_delivery_claim = or_(
        OutboxEvent.locked_at.is_not(None),
        OutboxEvent.next_attempt_at.is_not(None),
    )
    return or_(
        payload_marker.is_not(True),
        failed_with_free_text,
        stale_delivery_claim,
    )


def _outbox_event_needs_retention(event: OutboxEvent) -> bool:
    payload = event.payload_json
    payload_is_scrubbed = (
        isinstance(payload, Mapping) and payload.get(_PRIVACY_RETENTION_MARKER) is True
    )
    failed_with_free_text = (
        event.status == OutboxStatus.FAILED.value
        and event.last_error is not None
        and event.last_error != _PRIVACY_RETENTION_LAST_ERROR
    )
    stale_delivery_claim = (
        event.locked_at is not None or event.next_attempt_at is not None
    )
    return not payload_is_scrubbed or failed_with_free_text or stale_delivery_claim


def _apply_outbox_retention(event: OutboxEvent) -> None:
    event.payload_json = _scrubbed_outbox_payload(event.payload_json)
    event.locked_at = None
    event.next_attempt_at = None
    if event.status == OutboxStatus.FAILED.value:
        event.last_error = _PRIVACY_RETENTION_LAST_ERROR


def _scrubbed_outbox_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        payload = {}

    scrubbed = {
        key: value for key, value in payload.items() if key in _SAFE_OUTBOX_PAYLOAD_KEYS
    }
    scrubbed[_SCRUBBED_PAYLOAD_MARKER] = True
    scrubbed[_PRIVACY_RETENTION_MARKER] = True
    return scrubbed


async def _minimise_retained_audit_events(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    dry_run: bool,
) -> int:
    ids = await _retained_audit_event_ids(session, now=now, limit=limit)
    if dry_run or not ids:
        return len(ids)

    result = await session.execute(
        update(AuditEvent)
        .where(
            AuditEvent.id.in_(ids),
            *_retained_audit_event_filters(now),
        )
        .values(
            actor_user_id=None,
            reason=None,
            metadata_json=None,
            ip_address=None,
            user_agent=None,
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def _retained_audit_event_ids(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> tuple[Any, ...]:
    stmt = (
        select(AuditEvent.id)
        .where(*_retained_audit_event_filters(now))
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(limit)
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _retained_audit_event_filters(now: datetime) -> tuple[object, ...]:
    return (
        _audit_retention_age_condition(now),
        _audit_legal_hold_released_condition(now),
        _audit_event_needs_retention_condition(),
    )


def _audit_retention_age_condition(now: datetime) -> object:
    settings = get_settings().audit
    default_cutoff = now - timedelta(days=settings.retention_days)
    security_cutoff = now - timedelta(days=settings.security_retention_days)
    compliance_cutoff = now - timedelta(days=settings.compliance_retention_days)
    protected_categories = (
        AuditCategory.SECURITY.value,
        AuditCategory.COMPLIANCE.value,
    )
    return or_(
        and_(
            AuditEvent.category == AuditCategory.SECURITY.value,
            AuditEvent.created_at <= security_cutoff,
        ),
        and_(
            AuditEvent.category == AuditCategory.COMPLIANCE.value,
            AuditEvent.created_at <= compliance_cutoff,
        ),
        and_(
            AuditEvent.category.notin_(protected_categories),
            AuditEvent.created_at <= default_cutoff,
        ),
    )


def _audit_legal_hold_released_condition(now: datetime) -> object:
    return or_(
        AuditEvent.legal_hold_until.is_(None),
        AuditEvent.legal_hold_until <= now,
    )


def _audit_event_needs_retention_condition() -> object:
    return or_(
        AuditEvent.actor_user_id.is_not(None),
        AuditEvent.reason.is_not(None),
        AuditEvent.metadata_json.is_not(None),
        AuditEvent.ip_address.is_not(None),
        AuditEvent.user_agent.is_not(None),
    )


async def _clean_expired_dsr_idempotency_keys(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    dry_run: bool,
) -> int:
    ids = await _expired_dsr_idempotency_ids(session, now=now, limit=limit)
    if dry_run or not ids:
        return len(ids)

    result = await session.execute(
        update(DataSubjectRequest)
        .where(DataSubjectRequest.id.in_(ids))
        .values(
            idempotency_key_hash=None,
            idempotency_fingerprint=None,
            idempotency_key_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def _expired_dsr_idempotency_ids(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> tuple[Any, ...]:
    stmt = (
        select(DataSubjectRequest.id)
        .where(
            DataSubjectRequest.idempotency_key_expires_at.is_not(None),
            DataSubjectRequest.idempotency_key_expires_at <= now,
            or_(
                DataSubjectRequest.idempotency_key_hash.is_not(None),
                DataSubjectRequest.idempotency_fingerprint.is_not(None),
            ),
        )
        .order_by(
            DataSubjectRequest.idempotency_key_expires_at.asc(),
            DataSubjectRequest.id.asc(),
        )
        .limit(limit)
    )
    return tuple((await session.execute(stmt)).scalars().all())


def _normalise_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Privacy retention reference time must be timezone-aware")
    return value.astimezone(UTC)
