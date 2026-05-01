from __future__ import annotations

from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import _process_outbox_event


async def process_all_claimed_outbox_events(migrated_session_factory) -> None:
    async with migrated_session_factory() as session:
        async with session.begin():
            repo = OutboxEventRepository(session)
            claimed_events = await repo.claim_due_events(limit=500)

    for event in claimed_events:
        await _process_outbox_event(str(event.id))
