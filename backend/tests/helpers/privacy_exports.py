from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.models.export_artifact import ExportArtifact
from app.privacy.services.export_artifacts import (
    ExportArtifactService,
    PreparedExportArchive,
)


async def generate_export_artifact_in_committed_phases(
    session: AsyncSession,
    *,
    artifact: ExportArtifact,
    generated_by_user_id: UUID | None = None,
    processing_token: str | None = None,
) -> ExportArtifact:
    """Exercise the worker phases while preserving their commit boundaries."""

    service = ExportArtifactService(session)
    artifact_id = artifact.id
    token = processing_token or artifact.processing_token
    if token is None:
        leases = await service.claim_queued_artifact_leases(batch_size=1)
        lease = next(
            (candidate for candidate in leases if candidate.artifact_id == artifact_id),
            None,
        )
        if lease is None:
            raise AssertionError("Test export artifact was not claimed")
        token = lease.processing_token
    await session.commit()

    prepared: PreparedExportArchive | None = None
    try:
        prepared = await service.prepare_export_archive(
            artifact_id=artifact_id,
            processing_token=token,
        )
        await session.commit()
        await service.validate_prepared_export_upload(
            prepared=prepared,
            processing_token=token,
        )
        await session.commit()
        service.write_prepared_export_archive(prepared)
        ready = await service.mark_generated_export_artifact_ready(
            artifact_id=artifact_id,
            prepared=prepared,
            generated_by_user_id=generated_by_user_id,
            processing_token=token,
        )
        await session.commit()
        return ready
    except Exception as exc:
        await session.rollback()
        if prepared is not None:
            service.discard_prepared_export_archive(prepared)
        failed = await service.mark_export_artifact_failed(
            artifact_id=artifact_id,
            exc=exc,
            generated_by_user_id=generated_by_user_id,
            processing_token=token,
        )
        if failed is None:
            raise
        cleanup = service.failed_storage_cleanup(failed)
        await session.commit()
        if cleanup is None:
            return failed

        try:
            service.delete_failed_export_storage_object(cleanup)
        except Exception:
            return failed
        await service.clear_failed_export_storage_metadata(cleanup)
        await session.commit()
        return failed
