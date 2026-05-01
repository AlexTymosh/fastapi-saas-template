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

    async def claim_due_events(self, *, limit: int) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        statement = (
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

        bind = self.session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        # SQLite fallback is deterministic for tests;
        # production concurrency safety is PostgreSQL-specific.

        result = await self.session.execute(statement)
        events = list(result.scalars().all())
        for event in events:
            event.status = OutboxStatus.PROCESSING.value
            event.locked_at = now
        await self.session.flush()
        return events

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
