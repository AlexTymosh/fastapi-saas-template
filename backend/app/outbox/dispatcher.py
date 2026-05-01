from __future__ import annotations

import argparse
import asyncio

from app.core.db import get_session_factory
from app.core.logging import get_logger
from app.core.tasks import configure_broker
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import process_outbox_event

log = get_logger(__name__)


async def claim_and_enqueue_due_outbox_events(limit: int = 100) -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            events = await repository.claim_due_events(limit=limit)

    for event in events:
        process_outbox_event.send(str(event.id))
    return len(events)


async def run_dispatcher(*, interval: int, batch_size: int) -> None:
    log.info("outbox_dispatcher_started", interval=interval, batch_size=batch_size)
    while True:
        claimed = await claim_and_enqueue_due_outbox_events(limit=batch_size)
        log.info(
            "outbox_dispatcher_tick", claimed_count=claimed, enqueued_count=claimed
        )
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Outbox dispatcher")
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    configure_broker(require_redis=True)

    try:
        asyncio.run(run_dispatcher(interval=args.interval, batch_size=args.batch_size))
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("outbox_dispatcher_stopped")


if __name__ == "__main__":
    main()
