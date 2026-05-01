from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models.outbox_event import OutboxEvent, OutboxEventStatus


class OutboxEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_event(
        self,
        *,
        event_type: str,
        aggregate_type: str | None,
        aggregate_id: UUID | None,
        payload_json: dict[str, object],
        max_attempts: int = 10,
    ) -> OutboxEvent:
        event = OutboxEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_json=payload_json,
            max_attempts=max_attempts,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def get_by_id(self, event_id: UUID) -> OutboxEvent | None:
        return await self.session.get(OutboxEvent, event_id)

    async def mark_processing(self, event: OutboxEvent) -> None:
        if event.status == OutboxEventStatus.PROCESSED.value:
            return
        event.status = OutboxEventStatus.PROCESSING.value
        event.locked_at = datetime.now(UTC)
        await self.session.flush()

    async def mark_processed(self, event: OutboxEvent) -> None:
        event.status = OutboxEventStatus.PROCESSED.value
        event.processed_at = datetime.now(UTC)
        event.locked_at = None
        await self.session.flush()

    async def mark_retry(self, event: OutboxEvent, *, error_message: str) -> None:
        event.attempts += 1
        event.last_error = error_message
        event.locked_at = None
        if event.attempts >= event.max_attempts:
            event.status = OutboxEventStatus.FAILED.value
        else:
            event.status = OutboxEventStatus.PENDING.value
            delay = min(2**event.attempts, 300)
            event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        await self.session.flush()
