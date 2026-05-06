from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_events(
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
        return list(rows), total

    async def create(
        self,
        *,
        actor_user_id: UUID | None,
        category: AuditCategory,
        action: AuditAction,
        target_type: AuditTargetType,
        target_id: UUID | None,
        reason: str | None = None,
        metadata_json: dict[str, object] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEvent:
        audit_event = AuditEvent(
            actor_user_id=actor_user_id,
            category=category.value,
            action=action.value,
            target_type=target_type.value,
            target_id=target_id,
            reason=reason,
            metadata_json=metadata_json,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(audit_event)
        await self.session.flush()
        await self.session.refresh(audit_event)
        return audit_event
