from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

from app.core.db.session import get_session_factory
from app.privacy.services.export_artifacts import (
    DEFAULT_PROCESSING_LEASE_SECONDS,
    ExportArtifactService,
    FailedExportStorageCleanup,
    PreparedExportArchive,
    ProcessingExportLease,
)
from app.privacy.storage.base import (
    StorageObjectState,
    StoragePublicationReservation,
)

logger = logging.getLogger(__name__)


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
    prepared: PreparedExportArchive | None = None
    try:
        async with session_factory() as session:
            async with session.begin():
                prepared = await ExportArtifactService(session).prepare_export_archive(
                    artifact_id=lease.artifact_id,
                    processing_token=lease.processing_token,
                )
        return prepared
    except Exception:
        if prepared is not None:
            await asyncio.to_thread(
                ExportArtifactService.discard_prepared_export_archive,
                prepared,
            )
        raise


async def _write_export_archive(
    *, lease: ProcessingExportLease, prepared: PreparedExportArchive
) -> None:
    """Reserve storage, revalidate the intent, then publish with compare-and-swap."""

    session_factory = get_session_factory()
    service: ExportArtifactService
    reservation: StoragePublicationReservation | None = None
    publication_completed = False
    try:
        async with session_factory() as session:
            service = ExportArtifactService(session)
            reservation = await asyncio.to_thread(
                service.reserve_prepared_export_archive,
                prepared,
                processing_token=lease.processing_token,
            )
            async with session.begin():
                await service.validate_prepared_export_upload(
                    prepared=prepared,
                    processing_token=lease.processing_token,
                )
        await asyncio.to_thread(
            service.publish_prepared_export_archive,
            prepared,
            reservation,
        )
        publication_completed = True
    finally:
        if reservation is not None and not publication_completed:
            await asyncio.to_thread(
                service.cancel_prepared_export_archive_reservation,
                prepared,
                reservation,
            )
        await asyncio.to_thread(
            ExportArtifactService.discard_prepared_export_archive,
            prepared,
        )


async def _recover_committed_export_archive(*, prepared: PreparedExportArchive) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = ExportArtifactService(session)
        state = await asyncio.to_thread(
            service.inspect_committed_export_archive,
            prepared,
        )
    return state == StorageObjectState.MATCHING


async def _reset_committed_export_upload_intent(
    *,
    lease: ProcessingExportLease,
    prepared: PreparedExportArchive,
) -> None:
    """Fence the old key before allowing the active lease to choose a new one."""

    session_factory = get_session_factory()
    async with session_factory() as session:
        service = ExportArtifactService(session)
        await asyncio.to_thread(
            service.delete_prepared_export_storage_object,
            prepared,
        )
    async with session_factory() as session:
        async with session.begin():
            reset = await ExportArtifactService(
                session
            ).reset_prepared_export_upload_intent(
                prepared=prepared,
                processing_token=lease.processing_token,
            )
            if not reset:
                raise RuntimeError("export_upload_intent_reset_rejected")


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


async def _mark_export_failed(
    *, lease: ProcessingExportLease, exc: Exception
) -> FailedExportStorageCleanup | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            service = ExportArtifactService(session)
            failed = await service.mark_export_artifact_failed(
                artifact_id=lease.artifact_id,
                exc=exc,
                processing_token=lease.processing_token,
            )
            if failed is None:
                return None
            return service.failed_storage_cleanup(failed)


async def _delete_failed_export_storage(
    cleanup: FailedExportStorageCleanup,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = ExportArtifactService(session)
        await asyncio.to_thread(
            service.delete_failed_export_storage_object,
            cleanup,
        )


async def _clear_failed_export_storage_metadata(
    cleanup: FailedExportStorageCleanup,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            await ExportArtifactService(session).clear_failed_export_storage_metadata(
                cleanup
            )


async def _cleanup_failed_export_storage(
    cleanup: FailedExportStorageCleanup,
) -> None:
    try:
        await _delete_failed_export_storage(cleanup)
    except Exception as exc:
        logger.error(
            "Failed to delete failed export artifact storage object",
            extra={
                "artifact_id": str(cleanup.artifact_id),
                "storage_backend": cleanup.storage_backend,
                "error_type": type(exc).__name__,
            },
        )
        return

    try:
        await _clear_failed_export_storage_metadata(cleanup)
    except Exception as exc:
        logger.error(
            "Failed to clear failed export artifact storage metadata",
            extra={
                "artifact_id": str(cleanup.artifact_id),
                "storage_backend": cleanup.storage_backend,
                "error_type": type(exc).__name__,
            },
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
        if prepared.archive_path is None:
            recovered = await _recover_committed_export_archive(prepared=prepared)
            if not recovered:
                await _reset_committed_export_upload_intent(
                    lease=lease,
                    prepared=prepared,
                )
                prepared = await _prepare_export_archive(lease=lease)
        if prepared.archive_path is not None:
            await _write_export_archive(lease=lease, prepared=prepared)
        await _mark_export_ready(lease=lease, prepared=prepared)
    except Exception as exc:
        cleanup = await _mark_export_failed(lease=lease, exc=exc)
        if cleanup is not None:
            await _cleanup_failed_export_storage(cleanup)
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
