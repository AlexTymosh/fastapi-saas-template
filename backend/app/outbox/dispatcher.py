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
            claimed_events = await repository.claim_due_events(limit=limit)

    for event in claimed_events:
        process_outbox_event.send(str(event.id))

    return len(claimed_events)


async def run_dispatcher_loop(*, interval: int, batch_size: int) -> None:
    log.info("outbox_dispatcher_started", interval=interval, batch_size=batch_size)
    try:
        while True:
            claimed_count = await claim_and_enqueue_due_outbox_events(limit=batch_size)
            log.info(
                "outbox_dispatcher_tick",
                claimed_count=claimed_count,
                enqueued_count=claimed_count,
            )
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("outbox_dispatcher_cancelled")
        raise
    except KeyboardInterrupt:
        log.info("outbox_dispatcher_stopped")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Outbox dispatcher")
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    configure_broker(require_redis=True)
    asyncio.run(run_dispatcher_loop(interval=args.interval, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
