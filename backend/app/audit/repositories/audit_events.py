from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
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
        legal_hold_until: datetime | None = None,
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
            legal_hold_until=legal_hold_until,
        )
        self.session.add(audit_event)
        await self.session.flush()
        await self.session.refresh(audit_event)
        return audit_event

    async def anonymise_events_older_than(
        self,
        *,
        category: AuditCategory,
        created_before: datetime,
        now: datetime,
        batch_size: int,
    ) -> int:
        """Remove long-retained audit identifiers while keeping event integrity.

        The method selects a capped batch before updating so it remains portable
        across PostgreSQL and SQLite. Legal-hold records are skipped until their
        hold expires. Already anonymised rows are excluded so repeated runs are
        idempotent and do not consume future batches.

        The UPDATE repeats the eligibility predicates instead of filtering only
        by selected ids. This prevents a race where another transaction sets
        ``legal_hold_until`` after candidate selection but before anonymisation.
        """

        eligibility_predicates = (
            AuditEvent.category == category.value,
            AuditEvent.created_at < created_before,
            or_(
                AuditEvent.legal_hold_until.is_(None),
                AuditEvent.legal_hold_until <= now,
            ),
            or_(
                AuditEvent.actor_user_id.is_not(None),
                AuditEvent.reason.is_not(None),
                AuditEvent.metadata_json.is_not(None),
                AuditEvent.ip_address.is_not(None),
                AuditEvent.user_agent.is_not(None),
            ),
        )

        candidate_stmt = (
            select(AuditEvent.id)
            .where(*eligibility_predicates)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .limit(batch_size)
        )
        event_ids = list((await self.session.execute(candidate_stmt)).scalars().all())
        if not event_ids:
            return 0

        result = await self.session.execute(
            update(AuditEvent)
            .where(
                AuditEvent.id.in_(event_ids),
                *eligibility_predicates,
            )
            .values(
                actor_user_id=None,
                reason=None,
                metadata_json=None,
                ip_address=None,
                user_agent=None,
            )
            .execution_options(synchronize_session=False)
        )
        await self.session.flush()
        return int(result.rowcount or 0)
