from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.core.platform import (
    PlatformActor,
    PlatformPermission,
    PlatformWriteContext,
    require_platform_permission,
    require_platform_write_context,
)
from app.platform.schemas.platform_staff import (
    CreatePlatformStaffRequest,
    PlatformStaffCollectionResponse,
    PlatformStaffMeta,
    PlatformStaffResponse,
    ReasonRequest,
    UpdatePlatformStaffRoleRequest,
)
from app.platform.services.platform_staff import PlatformStaffService

router = APIRouter(prefix="/platform/staff", tags=["platform"])


@router.get(
    "", response_model=PlatformStaffCollectionResponse, responses=COMMON_ERROR_RESPONSES
)
async def list_platform_staff(
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.PLATFORM_STAFF_MANAGE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PlatformStaffCollectionResponse:
    staff_rows, total = await PlatformStaffService(db_session).list_staff(
        limit=limit, offset=offset
    )
    return PlatformStaffCollectionResponse(
        data=[PlatformStaffResponse.model_validate(staff) for staff in staff_rows],
        meta=PlatformStaffMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.post("", response_model=PlatformStaffResponse, responses=WRITE_ERROR_RESPONSES)
async def create_platform_staff(
    payload: CreatePlatformStaffRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_platform_write_context(PlatformPermission.PLATFORM_STAFF_MANAGE),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformStaffResponse:
    actor = write_context.actor
    staff = await PlatformStaffService(write_context.session).create_staff(
        actor=actor,
        user_id=payload.user_id,
        role=payload.role,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformStaffResponse.model_validate(staff)


@router.patch(
    "/{staff_id}/role",
    response_model=PlatformStaffResponse,
    responses=WRITE_ERROR_RESPONSES,
)
async def update_platform_staff_role(
    staff_id: UUID,
    payload: UpdatePlatformStaffRoleRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_platform_write_context(PlatformPermission.PLATFORM_STAFF_MANAGE),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformStaffResponse:
    actor = write_context.actor
    staff = await PlatformStaffService(write_context.session).change_role(
        staff_id=staff_id,
        actor=actor,
        role=payload.role,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformStaffResponse.model_validate(staff)


@router.post(
    "/{staff_id}/suspend",
    response_model=PlatformStaffResponse,
    responses=WRITE_ERROR_RESPONSES,
)
async def suspend_platform_staff(
    staff_id: UUID,
    payload: ReasonRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_platform_write_context(PlatformPermission.PLATFORM_STAFF_MANAGE),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformStaffResponse:
    actor = write_context.actor
    staff = await PlatformStaffService(write_context.session).suspend_staff(
        staff_id=staff_id,
        actor=actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformStaffResponse.model_validate(staff)


@router.post(
    "/{staff_id}/restore",
    response_model=PlatformStaffResponse,
    responses=WRITE_ERROR_RESPONSES,
)
async def restore_platform_staff(
    staff_id: UUID,
    payload: ReasonRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_platform_write_context(PlatformPermission.PLATFORM_STAFF_MANAGE),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformStaffResponse:
    actor = write_context.actor
    staff = await PlatformStaffService(write_context.session).restore_staff(
        staff_id=staff_id,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformStaffResponse.model_validate(staff)
