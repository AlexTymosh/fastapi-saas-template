from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditEvent


class PlatformAuditEventsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_audit_events(
        self,
        *,
        limit: int,
        offset: int,
        category: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
    ) -> tuple[list[AuditEvent], int]:
        stmt = select(AuditEvent)
        count_stmt = select(func.count()).select_from(AuditEvent)
        for attr, value in (
            (AuditEvent.category, category),
            (AuditEvent.action, action),
            (AuditEvent.target_type, target_type),
            (AuditEvent.target_id, target_id),
        ):
            if value is not None:
                stmt = stmt.where(attr == value)
                count_stmt = count_stmt.where(attr == value)

        rows = (
            (await self.session.execute(stmt.offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)
