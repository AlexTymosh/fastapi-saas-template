from __future__ import annotations

import argparse
import asyncio
import contextlib

from app.core.db.session import get_session_factory
from app.privacy.services.export_artifacts import (
    DEFAULT_PROCESSING_LEASE_SECONDS,
    ExportArtifactService,
    PreparedExportArchive,
    ProcessingExportLease,
)


async def _count_queued_artifacts(*, batch_size: int) -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            return await ExportArtifactService(session).count_queued_artifacts(
                limit=batch_size
            )


async def _claim_queued_artifact_leases(
    *, batch_size: int
) -> list[ProcessingExportLease]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            return await ExportArtifactService(session).claim_queued_artifact_leases(
                batch_size=batch_size
            )


async def _renew_processing_lease(*, lease: ProcessingExportLease) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            return await ExportArtifactService(session).renew_processing_lease(
                lease=lease
            )


async def _prepare_export_archive(
    *, lease: ProcessingExportLease
) -> PreparedExportArchive:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            return await ExportArtifactService(session).prepare_export_archive(
                artifact_id=lease.artifact_id,
                processing_token=lease.processing_token,
            )


async def _write_export_archive(prepared: PreparedExportArchive) -> None:
    """Write the archive outside of any database transaction."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = ExportArtifactService(session)
        await asyncio.to_thread(service.write_prepared_export_archive, prepared)


async def _mark_export_ready(
    *, lease: ProcessingExportLease, prepared: PreparedExportArchive
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            await ExportArtifactService(session).mark_generated_export_artifact_ready(
                artifact_id=prepared.artifact_id,
                prepared=prepared,
                processing_token=lease.processing_token,
            )


async def _mark_export_failed(*, lease: ProcessingExportLease, exc: Exception) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            await ExportArtifactService(session).mark_export_artifact_failed(
                artifact_id=lease.artifact_id,
                exc=exc,
                processing_token=lease.processing_token,
            )


async def _heartbeat_processing_lease(*, lease: ProcessingExportLease) -> None:
    interval = max(1, DEFAULT_PROCESSING_LEASE_SECONDS // 3)
    try:
        while True:
            await asyncio.sleep(interval)
            renewed = await _renew_processing_lease(lease=lease)
            if not renewed:
                return
    except asyncio.CancelledError:
        raise


async def _process_artifact(*, lease: ProcessingExportLease) -> None:
    heartbeat = asyncio.create_task(_heartbeat_processing_lease(lease=lease))
    try:
        prepared = await _prepare_export_archive(lease=lease)
        await _write_export_archive(prepared)
        await _mark_export_ready(lease=lease, prepared=prepared)
    except Exception as exc:
        await _mark_export_failed(lease=lease, exc=exc)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat


async def run_worker(
    *,
    batch_size: int,
    dry_run: bool,
    once: bool,
    poll_interval: float = 0.0,
) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if poll_interval < 0:
        raise ValueError("poll_interval must be greater than or equal to 0")

    total_processed = 0

    while True:
        if dry_run:
            processed_this_iteration = await _count_queued_artifacts(
                batch_size=batch_size
            )
        else:
            leases = await _claim_queued_artifact_leases(batch_size=batch_size)
            for lease in leases:
                await _process_artifact(lease=lease)
            processed_this_iteration = len(leases)

        total_processed += processed_this_iteration

        if dry_run or once:
            break
        if processed_this_iteration == 0:
            if poll_interval <= 0:
                break
            await asyncio.sleep(poll_interval)

    print(
        "privacy_export_worker "
        f"processed={total_processed} "
        f"dry_run={dry_run} "
        f"once={once} "
        f"poll_interval={poll_interval}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Privacy export artifact worker")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.0,
        help=(
            "Seconds to wait before polling again when no queued artifacts are "
            "available. A value of 0 keeps the worker one-shot/drain-only."
        ),
    )
    args = parser.parse_args()
    return asyncio.run(
        run_worker(
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            once=args.once,
            poll_interval=args.poll_interval,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
