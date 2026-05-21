from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.services.audit_events import AuditEventService
from app.core.config.settings import AuditSettings


async def anonymise_expired_audit_events(
    session: AsyncSession,
    *,
    settings: AuditSettings,
    now: datetime | None = None,
) -> int:
    """Anonymise audit events that are older than configured retention windows.

    The helper intentionally receives an already-managed SQLAlchemy session so it
    can be reused by a CLI task, a scheduled worker, or an explicit maintenance
    job without creating hidden transaction boundaries.
    """

    service = AuditEventService(session)
    return await service.anonymise_expired_events(
        settings=settings,
        now=_normalise_utc(now),
    )


def _normalise_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Audit retention reference time must be timezone-aware")

    return value.astimezone(UTC)
