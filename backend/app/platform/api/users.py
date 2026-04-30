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
    require_platform_permission,
)
from app.core.platform.write_context import (
    PlatformWriteContext,
    require_platform_write_context,
)
from app.platform.schemas.platform_users import (
    PlatformUserResponse,
    PlatformUsersCollectionResponse,
    PlatformUsersMeta,
    ReasonRequest,
)
from app.platform.services.platform_users import PlatformUsersService

router = APIRouter(prefix="/platform/users", tags=["platform"])


@router.get(
    "", response_model=PlatformUsersCollectionResponse, responses=COMMON_ERROR_RESPONSES
)
async def list_platform_users(
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.USERS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PlatformUsersCollectionResponse:
    users, total = await PlatformUsersService(db_session).list_users(
        limit=limit, offset=offset
    )
    return PlatformUsersCollectionResponse(
        data=[PlatformUserResponse.model_validate(user) for user in users],
        meta=PlatformUsersMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "/{user_id}", response_model=PlatformUserResponse, responses=COMMON_ERROR_RESPONSES
)
async def get_platform_user(
    user_id: UUID,
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.USERS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformUserResponse:
    user = await PlatformUsersService(db_session).get_user(user_id)
    return PlatformUserResponse.model_validate(user)


@router.post(
    "/{user_id}/suspend",
    response_model=PlatformUserResponse,
    responses=WRITE_ERROR_RESPONSES,
)
async def suspend_platform_user(
    user_id: UUID,
    payload: ReasonRequest,
    context: Annotated[
        PlatformWriteContext,
        Depends(require_platform_write_context(PlatformPermission.USERS_SUSPEND)),
    ],
    request: Request,
) -> PlatformUserResponse:
    user = await PlatformUsersService(context.session).suspend_user(
        user_id=user_id,
        actor=context.actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=context.actor.user.id, request=request
        ),
    )
    return PlatformUserResponse.model_validate(user)


@router.post(
    "/{user_id}/restore",
    response_model=PlatformUserResponse,
    responses=WRITE_ERROR_RESPONSES,
)
async def restore_platform_user(
    user_id: UUID,
    payload: ReasonRequest,
    context: Annotated[
        PlatformWriteContext,
        Depends(require_platform_write_context(PlatformPermission.USERS_RESTORE)),
    ],
    request: Request,
) -> PlatformUserResponse:
    user = await PlatformUsersService(context.session).restore_user(
        user_id=user_id,
        actor=context.actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=context.actor.user.id, request=request
        ),
    )
    return PlatformUserResponse.model_validate(user)
