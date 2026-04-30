from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditEvent
from app.audit.repositories.audit_events import AuditEventsRepository


class AuditEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = AuditEventsRepository(session)

    async def record_event(
        self,
        *,
        actor_user_id: UUID | None,
        category: AuditCategory,
        action: AuditAction,
        target_type: str,
        target_id: UUID | None,
        reason: str | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> AuditEvent:
        return await self.repository.create(
            actor_user_id=actor_user_id,
            category=category,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            metadata_json=metadata_json,
        )
