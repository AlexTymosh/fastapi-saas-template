from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.core.db.session import get_session_factory
from app.privacy.services.export_artifacts import (
    ExportArtifactService,
    PreparedExportArchive,
)


async def _count_queued_artifacts(*, batch_size: int) -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            return await ExportArtifactService(session).count_queued_artifacts(
                limit=batch_size
            )


async def _claim_queued_artifact_ids(*, batch_size: int) -> list[UUID]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            return await ExportArtifactService(session).claim_queued_artifact_ids(
                batch_size=batch_size
            )


async def _prepare_export_archive(*, artifact_id: UUID) -> PreparedExportArchive:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            return await ExportArtifactService(session).prepare_export_archive(
                artifact_id=artifact_id
            )


async def _write_export_archive(prepared: PreparedExportArchive) -> None:
    """Write the archive outside of any database transaction.

    Keeping storage IO out of the claim/mark-ready transactions prevents future
    large exports from holding row locks or an open transaction while writing to
    object storage.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        ExportArtifactService(session).write_prepared_export_archive(prepared)


async def _mark_export_ready(*, prepared: PreparedExportArchive) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            await ExportArtifactService(session).mark_generated_export_artifact_ready(
                artifact_id=prepared.artifact_id,
                prepared=prepared,
            )


async def _mark_export_failed(*, artifact_id: UUID, exc: Exception) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            await ExportArtifactService(session).mark_export_artifact_failed(
                artifact_id=artifact_id,
                exc=exc,
            )


async def _process_artifact(*, artifact_id: UUID) -> None:
    try:
        prepared = await _prepare_export_archive(artifact_id=artifact_id)
        await _write_export_archive(prepared)
        await _mark_export_ready(prepared=prepared)
    except Exception as exc:
        await _mark_export_failed(artifact_id=artifact_id, exc=exc)


async def run_worker(*, batch_size: int, dry_run: bool, once: bool) -> int:
    total_processed = 0

    while True:
        if dry_run:
            processed_this_iteration = await _count_queued_artifacts(
                batch_size=batch_size
            )
        else:
            artifact_ids = await _claim_queued_artifact_ids(batch_size=batch_size)
            for artifact_id in artifact_ids:
                await _process_artifact(artifact_id=artifact_id)
            processed_this_iteration = len(artifact_ids)

        total_processed += processed_this_iteration

        if dry_run or once or processed_this_iteration == 0:
            break

    print(
        "privacy_export_worker "
        f"processed={total_processed} dry_run={dry_run} once={once}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Privacy export artifact worker")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        run_worker(batch_size=args.batch_size, dry_run=args.dry_run, once=args.once)
    )


if __name__ == "__main__":
    raise SystemExit(main())
