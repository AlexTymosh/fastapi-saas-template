from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.privacy.services.export_artifacts import (
    ExportArtifactService,
    ExportArtifactStoragePurge,
)

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
_logger = logging.getLogger(__name__)


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
    """Run the database phase of privacy retention.

    Transaction ownership remains with the caller so this helper can be reused
    inside an explicit unit of work. External storage is never touched here.

    Dry-run mode includes already non-downloadable storage retry rows in the
    preview count. The full runner commits this database phase before it performs
    storage deletion and conditionally clears matching metadata afterward.
    """

    if limit < 1:
        raise ValueError("Privacy retention batch size must be positive")

    reference_now = _normalise_utc(now)
    database_summary = await _run_non_export_retention(
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
        anonymised_invites=database_summary.anonymised_invites,
        scrubbed_outbox_events=database_summary.scrubbed_outbox_events,
        minimised_audit_events=database_summary.minimised_audit_events,
        cleaned_dsr_idempotency_keys=(database_summary.cleaned_dsr_idempotency_keys),
    )


async def run_privacy_retention_pass(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    limit: int = 1000,
    dry_run: bool = False,
) -> PrivacyRetentionMaintenanceSummary:
    """Run one bounded retention pass with storage I/O between transactions."""

    if limit < 1:
        raise ValueError("Privacy retention batch size must be positive")

    reference_now = _normalise_utc(now)
    if dry_run:
        async with session_factory() as session:
            summary = await run_privacy_retention_maintenance(
                session,
                now=reference_now,
                limit=limit,
                dry_run=True,
            )
            await session.rollback()
        return summary

    purge_failures: list[Exception] = []
    export_processed = 0

    async with session_factory() as session:
        async with session.begin():
            database_summary = await _run_non_export_retention(
                session,
                now=reference_now,
                limit=limit,
                dry_run=False,
            )
            service = ExportArtifactService(session)
            cancelled_purges = await service.list_cancelled_erasure_storage_purges(
                limit=limit,
            )

    deleted, failures = await _delete_export_storage_purges(
        session_factory,
        cancelled_purges,
    )
    purge_failures.extend(failures)

    async with session_factory() as session:
        async with session.begin():
            service = ExportArtifactService(session)
            cleared = await _clear_export_storage_purges(service, deleted)
            export_processed += cleared
            remaining_limit = limit - export_processed
            failed_purges = (
                await service.list_failed_storage_purges(limit=remaining_limit)
                if remaining_limit > 0
                else ()
            )

    deleted, failures = await _delete_export_storage_purges(
        session_factory,
        failed_purges,
    )
    purge_failures.extend(failures)

    async with session_factory() as session:
        async with session.begin():
            service = ExportArtifactService(session)
            cleared = await _clear_export_storage_purges(service, deleted)
            export_processed += cleared
            remaining_limit = limit - export_processed
            if remaining_limit > 0:
                newly_expired_ids = await service.expire_ready_artifacts(
                    now=reference_now,
                    limit=remaining_limit,
                )
            else:
                newly_expired_ids = ()
            export_processed += len(newly_expired_ids)
            remaining_limit = limit - export_processed
            expired_purges = (
                await service.list_expired_storage_purges(
                    limit=remaining_limit,
                    exclude_ids=set(newly_expired_ids),
                )
                if remaining_limit > 0
                else ()
            )

    deleted, failures = await _delete_export_storage_purges(
        session_factory,
        expired_purges,
    )
    purge_failures.extend(failures)

    async with session_factory() as session:
        async with session.begin():
            cleared = await _clear_export_storage_purges(
                ExportArtifactService(session),
                deleted,
            )
            export_processed += cleared

    summary = PrivacyRetentionMaintenanceSummary(
        expired_export_artifacts=export_processed,
        anonymised_invites=database_summary.anonymised_invites,
        scrubbed_outbox_events=database_summary.scrubbed_outbox_events,
        minimised_audit_events=database_summary.minimised_audit_events,
        cleaned_dsr_idempotency_keys=(database_summary.cleaned_dsr_idempotency_keys),
    )
    if summary.total == 0 and purge_failures:
        raise purge_failures[0]
    return summary


async def _run_non_export_retention(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    dry_run: bool,
) -> PrivacyRetentionMaintenanceSummary:
    anonymised_invites = await _anonymise_retained_invites(
        session,
        now=now,
        limit=limit,
        dry_run=dry_run,
    )
    scrubbed_outbox_events = await _scrub_retained_outbox_events(
        session,
        now=now,
        limit=limit,
        dry_run=dry_run,
    )
    minimised_audit_events = await _minimise_retained_audit_events(
        session,
        now=now,
        limit=limit,
        dry_run=dry_run,
    )
    cleaned_dsr_idempotency_keys = await _clean_expired_dsr_idempotency_keys(
        session,
        now=now,
        limit=limit,
        dry_run=dry_run,
    )

    return PrivacyRetentionMaintenanceSummary(
        expired_export_artifacts=0,
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
    """Expire ready exports without touching external storage.

    Transaction ownership remains with the caller so this helper can be reused
    inside an explicit unit of work.

    Dry-run mode previews all export retention work. The full retention runner
    handles already non-downloadable object purges after a committed snapshot.
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


async def _delete_export_storage_purges(
    session_factory: async_sessionmaker[AsyncSession],
    purges: tuple[ExportArtifactStoragePurge, ...],
) -> tuple[tuple[ExportArtifactStoragePurge, ...], list[Exception]]:
    deleted: list[ExportArtifactStoragePurge] = []
    failures: list[Exception] = []
    if not purges:
        return (), failures

    async with session_factory() as session:
        service = ExportArtifactService(session)
        if session.in_transaction():
            raise RuntimeError(
                "Export storage purge cannot run inside a database transaction"
            )
        for purge in purges:
            try:
                await asyncio.to_thread(
                    service.delete_export_storage_purge_object,
                    purge,
                )
            except Exception as exc:
                failures.append(exc)
                _logger.exception(
                    "Failed to purge export artifact storage object",
                    extra={
                        "artifact_id": str(purge.artifact_id),
                        "storage_backend": purge.storage_backend,
                    },
                )
                continue
            deleted.append(purge)
    return tuple(deleted), failures


async def _clear_export_storage_purges(
    service: ExportArtifactService,
    purges: tuple[ExportArtifactStoragePurge, ...],
) -> int:
    cleared = 0
    for purge in purges:
        if await service.clear_export_storage_purge_metadata(purge):
            cleared += 1
    return cleared


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
