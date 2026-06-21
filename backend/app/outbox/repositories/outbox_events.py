from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models.outbox_event import (
    OutboxDeliveryClaim,
    OutboxEvent,
    OutboxEventType,
    OutboxStatus,
)

_INVITE_OUTBOX_EVENT_TYPES = frozenset(
    {
        OutboxEventType.INVITE_CREATED.value,
        OutboxEventType.INVITE_RESEND.value,
    }
)
_SENSITIVE_INVITE_PAYLOAD_KEYS = frozenset({"email", "encrypted_raw_token"})


def _scrub_sensitive_delivery_payload(event: OutboxEvent) -> None:
    """Remove delivery-only secrets from terminal invite outbox events."""
    if event.event_type not in _INVITE_OUTBOX_EVENT_TYPES:
        return

    payload = event.payload_json
    if not isinstance(payload, dict):
        return

    scrubbed_payload = {
        key: value
        for key, value in payload.items()
        if key not in _SENSITIVE_INVITE_PAYLOAD_KEYS
    }
    scrubbed_payload["sensitive_payload_scrubbed"] = True
    event.payload_json = scrubbed_payload


class OutboxEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _is_postgresql(self) -> bool:
        bind = self.session.bind
        return bool(bind and bind.dialect.name == "postgresql")

    async def create_event(self, *, event: OutboxEvent) -> OutboxEvent:
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def get_by_id(self, event_id: UUID) -> OutboxEvent | None:
        result = await self.session.execute(
            select(OutboxEvent).where(OutboxEvent.id == event_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_pending_due_events(self, *, limit: int) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING.value,
                (
                    (OutboxEvent.next_attempt_at.is_(None))
                    | (OutboxEvent.next_attempt_at <= now)
                ),
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def claim_due_events(self, *, limit: int) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        due_query = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING.value,
                (
                    (OutboxEvent.next_attempt_at.is_(None))
                    | (OutboxEvent.next_attempt_at <= now)
                ),
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )
        if self._is_postgresql():
            due_query = due_query.with_for_update(skip_locked=True)
        # SQLite and other lightweight test dialects do not provide the same
        # row-level concurrency semantics as PostgreSQL SKIP LOCKED.
        result = await self.session.execute(due_query)
        claimed = list(result.scalars().all())
        for event in claimed:
            await self._clear_delivery_claim(event_id=event.id)
            event.status = OutboxStatus.PROCESSING.value
            event.locked_at = now
            event.updated_at = now
        await self.session.flush()
        return claimed

    async def claim_processing_event_for_delivery(
        self, *, event_id: UUID, claim_token: str
    ) -> OutboxEvent | None:
        """Atomically reserve one processing event for external delivery.

        The row lock is held only while recording worker ownership. The caller
        can perform slow external I/O after the transaction commits.
        """
        now = datetime.now(UTC)
        event_query = select(OutboxEvent).where(OutboxEvent.id == event_id).limit(1)
        if self._is_postgresql():
            event_query = event_query.with_for_update()

        event = (await self.session.execute(event_query)).scalar_one_or_none()
        if event is None or event.status != OutboxStatus.PROCESSING.value:
            return None

        existing_claim = (
            await self.session.execute(
                select(OutboxDeliveryClaim)
                .where(OutboxDeliveryClaim.event_id == event_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_claim is not None:
            return None

        self.session.add(
            OutboxDeliveryClaim(
                event_id=event_id,
                claim_token=claim_token,
                claimed_at=now,
            )
        )
        event.locked_at = now
        event.updated_at = now
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def get_delivery_claimed_event(
        self, *, event_id: UUID, claim_token: str
    ) -> OutboxEvent | None:
        result = await self.session.execute(
            select(OutboxEvent)
            .join(
                OutboxDeliveryClaim,
                OutboxDeliveryClaim.event_id == OutboxEvent.id,
            )
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxStatus.PROCESSING.value,
                OutboxDeliveryClaim.claim_token == claim_token,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _clear_delivery_claim(self, *, event_id: UUID) -> None:
        await self.session.execute(
            delete(OutboxDeliveryClaim).where(OutboxDeliveryClaim.event_id == event_id)
        )

    async def mark_processing(self, *, event: OutboxEvent) -> None:
        if event.status == OutboxStatus.PROCESSED.value:
            return
        await self._clear_delivery_claim(event_id=event.id)
        event.status = OutboxStatus.PROCESSING.value
        event.locked_at = datetime.now(UTC)
        await self.session.flush()

    async def mark_processed(self, *, event: OutboxEvent) -> None:
        now = datetime.now(UTC)
        await self._clear_delivery_claim(event_id=event.id)
        event.status = OutboxStatus.PROCESSED.value
        event.processed_at = now
        event.locked_at = None
        event.last_error = None
        event.updated_at = now
        _scrub_sensitive_delivery_payload(event)
        await self.session.flush()

    async def mark_failed_attempt(self, *, event: OutboxEvent, error: str) -> None:
        now = datetime.now(UTC)
        attempts = event.attempts + 1
        await self._clear_delivery_claim(event_id=event.id)
        event.attempts = attempts
        event.locked_at = None
        event.last_error = error[:500]
        if attempts >= event.max_attempts:
            event.status = OutboxStatus.FAILED.value
            event.next_attempt_at = None
            _scrub_sensitive_delivery_payload(event)
        else:
            event.status = OutboxStatus.PENDING.value
            event.next_attempt_at = now + timedelta(seconds=2**attempts)
        event.updated_at = now
        await self.session.flush()

    async def release_processing_event_for_retry(
        self, *, event: OutboxEvent, error: str
    ) -> None:
        if event.status != OutboxStatus.PROCESSING.value:
            return
        await self.mark_failed_attempt(event=event, error=error)

    async def recover_stale_processing_events(
        self, *, stale_timeout_seconds: float, limit: int
    ) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=stale_timeout_seconds)
        stale_query = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PROCESSING.value,
                OutboxEvent.locked_at.is_not(None),
                OutboxEvent.locked_at < stale_before,
            )
            .order_by(OutboxEvent.locked_at.asc())
            .limit(limit)
        )
        if self._is_postgresql():
            stale_query = stale_query.with_for_update(skip_locked=True)
        result = await self.session.execute(stale_query)
        stale_events = list(result.scalars().all())
        for event in stale_events:
            await self.mark_failed_attempt(
                event=event, error="stale_processing_recovered"
            )
        return stale_events
