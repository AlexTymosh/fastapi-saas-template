from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.services.export_artifacts import ExportArtifactService


async def expire_ready_export_artifacts(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 1000,
    dry_run: bool = False,
) -> int:
    """Expire ready exports and retry cancelled erasure export purges.

    Transaction ownership remains with the caller so this helper can be reused
    by a CLI command, scheduled worker, or explicit maintenance job.

    Dry-run mode performs a non-mutating database preview and deliberately does
    not touch external storage.
    """

    reference_now = _normalise_utc(now)
    service = ExportArtifactService(session)
    if dry_run:
        return await service.count_expired_ready_artifacts(
            now=reference_now,
            limit=limit,
        )
    return await service.mark_expired_artifacts(
        now=reference_now,
        limit=limit,
    )


def _normalise_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Privacy retention reference time must be timezone-aware")
    return value.astimezone(UTC)
