from __future__ import annotations

import argparse
import asyncio

from app.core.db import get_session_factory
from app.core.config.settings import get_settings
from app.core.logging import get_logger
from app.core.tasks import configure_broker
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import process_outbox_event

log = get_logger(__name__)


async def recover_stale_processing_events() -> int:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            recovered = await repository.recover_stale_processing_events(
                stale_timeout_seconds=settings.outbox.stale_processing_timeout_seconds,
                limit=settings.outbox.recovery_batch_size,
            )
    recovered_count = len(recovered)
    if recovered_count > 0:
        log.info(
            "outbox_stale_processing_recovered",
            recovered_count=recovered_count,
            stale_timeout_seconds=settings.outbox.stale_processing_timeout_seconds,
        )
    return recovered_count


async def claim_and_enqueue_due_outbox_events(limit: int = 100) -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            claimed_events = await repository.claim_due_events(limit=limit)

    released_count = 0
    enqueued_count = 0
    for event in claimed_events:
        try:
            process_outbox_event.send(str(event.id))
            enqueued_count += 1
        except Exception as exc:
            log.warning(
                "outbox_enqueue_failed",
                event_id=str(event.id),
                error_type=type(exc).__name__,
            )
            async with session_factory() as session:
                async with session.begin():
                    repository = OutboxEventRepository(session)
                    persisted_event = await repository.get_by_id(event.id)
                    if persisted_event is not None:
                        await repository.release_processing_event_for_retry(
                            event=persisted_event,
                            error=f"enqueue_failed:{type(exc).__name__}",
                        )
                        released_count += 1

    log.info(
        "outbox_dispatcher_claim_enqueued",
        claimed_count=len(claimed_events),
        enqueued_count=enqueued_count,
        released_count=released_count,
    )

    return enqueued_count


async def run_dispatcher_loop(*, interval: int, batch_size: int) -> None:
    log.info("outbox_dispatcher_started", interval=interval, batch_size=batch_size)
    try:
        while True:
            recovered_count = await recover_stale_processing_events()
            enqueued_count = await claim_and_enqueue_due_outbox_events(limit=batch_size)
            log.info(
                "outbox_dispatcher_tick",
                recovered_count=recovered_count,
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
