from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models.outbox_event import OutboxEvent, OutboxStatus


class OutboxEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        if self.session.bind and self.session.bind.dialect.name == "postgresql":
            due_query = due_query.with_for_update(skip_locked=True)
        # SQLite and other lightweight test dialects do not provide the same
        # row-level concurrency semantics as PostgreSQL SKIP LOCKED.
        result = await self.session.execute(due_query)
        claimed = list(result.scalars().all())
        for event in claimed:
            event.status = OutboxStatus.PROCESSING.value
            event.locked_at = now
            event.updated_at = now
        await self.session.flush()
        return claimed

    async def mark_processing(self, *, event: OutboxEvent) -> None:
        if event.status == OutboxStatus.PROCESSED.value:
            return
        event.status = OutboxStatus.PROCESSING.value
        event.locked_at = datetime.now(UTC)
        await self.session.flush()

    async def mark_processed(self, *, event: OutboxEvent) -> None:
        now = datetime.now(UTC)
        event.status = OutboxStatus.PROCESSED.value
        event.processed_at = now
        event.locked_at = None
        event.last_error = None
        event.updated_at = now
        await self.session.flush()

    async def mark_failed_attempt(self, *, event: OutboxEvent, error: str) -> None:
        now = datetime.now(UTC)
        attempts = event.attempts + 1
        event.attempts = attempts
        event.locked_at = None
        event.last_error = error[:500]
        if attempts >= event.max_attempts:
            event.status = OutboxStatus.FAILED.value
            event.next_attempt_at = None
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
        if self.session.bind and self.session.bind.dialect.name == "postgresql":
            stale_query = stale_query.with_for_update(skip_locked=True)
        result = await self.session.execute(stale_query)
        stale_events = list(result.scalars().all())
        for event in stale_events:
            await self.mark_failed_attempt(
                event=event, error="stale_processing_recovered"
            )
        return stale_events
