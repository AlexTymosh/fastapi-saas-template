from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.repositories.outbox_events import OutboxEventRepository


class OutboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = OutboxEventRepository(session)

    async def publish(
        self,
        *,
        event_type: str,
        aggregate_type: str | None,
        aggregate_id: UUID | None,
        payload_json: dict[str, object],
    ) -> None:
        await self.repository.create_event(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_json=payload_json,
        )
