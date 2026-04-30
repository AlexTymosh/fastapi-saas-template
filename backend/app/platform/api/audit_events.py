from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditEvent
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES
from app.core.platform import PlatformPermission, require_platform_permission
from app.platform.schemas.platform_audit_events import (
    PlatformAuditEventResponse,
    PlatformAuditEventsCollectionResponse,
    PlatformAuditEventsMeta,
)

router = APIRouter(prefix="/platform/audit-events", tags=["platform"])


@router.get(
    "",
    response_model=PlatformAuditEventsCollectionResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def list_platform_audit_events(
    _: Annotated[
        object, Depends(require_platform_permission(PlatformPermission.AUDIT_READ))
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
) -> PlatformAuditEventsCollectionResponse:
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
    rows = (await db_session.execute(stmt.offset(offset).limit(limit))).scalars().all()
    total = (await db_session.execute(count_stmt)).scalar_one()
    return PlatformAuditEventsCollectionResponse(
        data=[PlatformAuditEventResponse.model_validate(row) for row in rows],
        meta=PlatformAuditEventsMeta(total=total, limit=limit, offset=offset),
        links={},
    )
