from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.db import get_db_session
from app.core.errors.openapi import (
    COMMON_ERROR_RESPONSES,
    RATE_LIMIT_ERROR_RESPONSES,
    WRITE_ERROR_RESPONSES,
)
from app.core.platform import (
    PlatformActor,
    PlatformPermission,
    PlatformWriteContext,
    require_any_platform_permission,
    require_platform_permission,
    require_rate_limited_platform_write_context,
)
from app.core.rate_limit import PLATFORM_READ_POLICY, rate_limit_dependency
from app.platform.schemas.platform_query import (
    PlatformFullUserListQuery,
    PlatformLimitedUserListQuery,
)
from app.platform.schemas.platform_users import (
    PlatformLimitedUserResponse,
    PlatformLimitedUsersCollectionResponse,
    PlatformUserResponse,
    PlatformUsersCollectionResponse,
    PlatformUsersMeta,
    ReasonRequest,
)
from app.platform.services.platform_users import PlatformUsersService

router = APIRouter(prefix="/platform/users", tags=["platform-users"])


@router.get(
    "/limited",
    response_model=PlatformLimitedUsersCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="list_limited_platform_users",
)
async def list_limited_platform_users(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        PlatformActor,
        Depends(
            require_any_platform_permission(
                PlatformPermission.USERS_READ_LIMITED,
                PlatformPermission.USERS_READ,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    query: Annotated[PlatformLimitedUserListQuery, Query()],
) -> PlatformLimitedUsersCollectionResponse:
    users, total = await PlatformUsersService(db_session).list_limited_users(
        limit=query.limit,
        offset=query.offset,
        status=query.status,
        q=query.q,
        exact_email=query.exact_email,
    )
    return PlatformLimitedUsersCollectionResponse(
        data=[PlatformLimitedUserResponse.from_user(user) for user in users],
        meta=PlatformUsersMeta(total=total, limit=query.limit, offset=query.offset),
        links={},
    )


@router.get(
    "",
    response_model=PlatformUsersCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="list_platform_users",
)
async def list_platform_users(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.USERS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    query: Annotated[PlatformFullUserListQuery, Query()],
) -> PlatformUsersCollectionResponse:
    users, total = await PlatformUsersService(db_session).list_users(
        limit=query.limit, offset=query.offset, status=query.status, q=query.q
    )
    return PlatformUsersCollectionResponse(
        data=[PlatformUserResponse.model_validate(user) for user in users],
        meta=PlatformUsersMeta(total=total, limit=query.limit, offset=query.offset),
        links={},
    )


@router.get(
    "/{user_id}",
    response_model=PlatformUserResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="get_platform_user",
)
async def get_platform_user(
    user_id: UUID,
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
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
    status_code=status.HTTP_200_OK,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="suspend_platform_user",
)
async def suspend_platform_user(
    user_id: UUID,
    payload: ReasonRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.USERS_SUSPEND
            ),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformUserResponse:
    actor = write_context.actor
    user = await PlatformUsersService(write_context.session).suspend_user(
        user_id=user_id,
        actor=actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformUserResponse.model_validate(user)


@router.post(
    "/{user_id}/restore",
    response_model=PlatformUserResponse,
    status_code=status.HTTP_200_OK,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="restore_platform_user",
)
async def restore_platform_user(
    user_id: UUID,
    payload: ReasonRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.USERS_RESTORE
            ),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformUserResponse:
    actor = write_context.actor
    user = await PlatformUsersService(write_context.session).restore_user(
        user_id=user_id,
        actor=actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformUserResponse.model_validate(user)
