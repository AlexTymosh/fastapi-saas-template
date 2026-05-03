from __future__ import annotations

import argparse
import asyncio

from app.core.db import get_session_factory
from app.core.logging import get_logger
from app.core.tasks import configure_broker
from app.core.config.settings import get_settings
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import process_outbox_event

log = get_logger(__name__)


async def claim_and_enqueue_due_outbox_events(limit: int = 100) -> int:
    session_factory = get_session_factory()
    released_count = 0
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            claimed_events = await repository.claim_due_events(limit=limit)

    for event in claimed_events:
        try:
            process_outbox_event.send(str(event.id))
        except Exception as exc:
            released_count += 1
            log.warning(
                "outbox_enqueue_failed",
                event_id=str(event.id),
                error_type=type(exc).__name__,
            )
            async with session_factory() as session:
                async with session.begin():
                    repository = OutboxEventRepository(session)
                    claimed_event = await repository.get_by_id(event.id)
                    if claimed_event is None:
                        continue
                    await repository.release_processing_event_for_retry(
                        event=claimed_event,
                        error=f"enqueue_failed:{type(exc).__name__}",
                    )

    enqueued_count = len(claimed_events) - released_count
    log.info(
        "outbox_dispatcher_enqueue_summary",
        claimed_count=len(claimed_events),
        enqueued_count=enqueued_count,
        released_count=released_count,
    )
    return enqueued_count


async def run_dispatcher_loop(*, interval: int, batch_size: int) -> None:
    log.info("outbox_dispatcher_started", interval=interval, batch_size=batch_size)
    try:
        while True:
            async with get_session_factory()() as session:
                async with session.begin():
                    repository = OutboxEventRepository(session)
                    recovered_events = await repository.recover_stale_processing_events(
                        stale_timeout_seconds=get_settings().outbox.stale_processing_timeout_seconds,
                        limit=get_settings().outbox.recovery_batch_size,
                    )
            log.info(
                "outbox_stale_processing_recovered",
                recovered_count=len(recovered_events),
                stale_timeout_seconds=get_settings().outbox.stale_processing_timeout_seconds,
            )
            enqueued_count = await claim_and_enqueue_due_outbox_events(limit=batch_size)
            log.info(
                "outbox_dispatcher_tick",
                enqueued_count=enqueued_count,
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
