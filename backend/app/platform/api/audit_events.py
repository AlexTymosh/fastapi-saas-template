from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditEvent
from app.audit.services.audit_events import AuditEventService
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, RATE_LIMIT_ERROR_RESPONSES
from app.core.platform import PlatformPermission, require_platform_permission
from app.core.rate_limit import AUDIT_READ_POLICY, rate_limit_dependency
from app.platform.schemas.platform_audit_events import (
    PlatformAuditEventResponse,
    PlatformAuditEventsCollectionResponse,
    PlatformAuditEventsMeta,
    PlatformLimitedAuditEventResponse,
    PlatformLimitedAuditEventsCollectionResponse,
)

router = APIRouter(prefix="/platform/audit-events", tags=["platform"])


async def _list_audit_events(
    *,
    db_session: AsyncSession,
    limit: int,
    offset: int,
    category: str | None,
    action: str | None,
    target_type: str | None,
    target_id: UUID | None,
) -> tuple[list[AuditEvent], int]:
    return await AuditEventService(db_session).list_events(
        limit=limit,
        offset=offset,
        category=category,
        action=action,
        target_type=target_type,
        target_id=target_id,
    )


@router.get(
    "/limited",
    response_model=PlatformLimitedAuditEventsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_limited_platform_audit_events(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(AUDIT_READ_POLICY))],
    _: Annotated[
        object,
        Depends(require_platform_permission(PlatformPermission.AUDIT_READ_LIMITED)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
) -> PlatformLimitedAuditEventsCollectionResponse:
    rows, total = await _list_audit_events(
        db_session=db_session,
        limit=limit,
        offset=offset,
        category=category,
        action=action,
        target_type=target_type,
        target_id=target_id,
    )
    return PlatformLimitedAuditEventsCollectionResponse(
        data=[PlatformLimitedAuditEventResponse.from_audit_event(row) for row in rows],
        meta=PlatformAuditEventsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "",
    response_model=PlatformAuditEventsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_platform_audit_events(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(AUDIT_READ_POLICY))],
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
    rows, total = await _list_audit_events(
        db_session=db_session,
        limit=limit,
        offset=offset,
        category=category,
        action=action,
        target_type=target_type,
        target_id=target_id,
    )
    return PlatformAuditEventsCollectionResponse(
        data=[PlatformAuditEventResponse.model_validate(row) for row in rows],
        meta=PlatformAuditEventsMeta(total=total, limit=limit, offset=offset),
        links={},
    )
