from __future__ import annotations

from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import _process_outbox_event
from tests.helpers.asyncio_runner import run_async


async def process_all_claimed_outbox_events(migrated_session_factory) -> None:
    async with migrated_session_factory() as session:
        async with session.begin():
            repo = OutboxEventRepository(session)
            events = await repo.claim_due_events(limit=500)

    for event in events:
        await _process_outbox_event(str(event.id))


def drain_outbox(migrated_session_factory, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory",
        lambda: migrated_session_factory,
    )
    run_async(process_all_claimed_outbox_events(migrated_session_factory))
