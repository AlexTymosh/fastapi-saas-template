from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.db import get_db_session
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform import PlatformPermission, require_platform_permission
from app.platform.schemas.platform_users import PlatformUserResponse, ReasonRequest
from app.users.models.user import User, UserStatus

router = APIRouter(prefix="/platform/users", tags=["platform"])


@router.get("", response_model=list[PlatformUserResponse])
async def list_platform_users(
    _: Annotated[
        object, Depends(require_platform_permission(PlatformPermission.USERS_READ))
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[PlatformUserResponse]:
    result = await db_session.execute(select(User).limit(100))
    return [
        PlatformUserResponse.model_validate(user) for user in result.scalars().all()
    ]


@router.get("/{user_id}", response_model=PlatformUserResponse)
async def get_platform_user(
    user_id: UUID,
    _: Annotated[
        object, Depends(require_platform_permission(PlatformPermission.USERS_READ))
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformUserResponse:
    user = await db_session.get(User, user_id)
    if user is None:
        raise NotFoundError(detail="User not found")
    return PlatformUserResponse.model_validate(user)


@router.post("/{user_id}/suspend", response_model=PlatformUserResponse)
async def suspend_platform_user(
    user_id: UUID,
    payload: ReasonRequest,
    actor: Annotated[
        object, Depends(require_platform_permission(PlatformPermission.USERS_SUSPEND))
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformUserResponse:
    user = await db_session.get(User, user_id)
    if user is None:
        raise NotFoundError(detail="User not found")
    if user.status == UserStatus.SUSPENDED:
        raise ConflictError(detail="User already suspended")
    async with db_session.begin():
        user.status = UserStatus.SUSPENDED
        user.suspended_at = datetime.now(UTC)
        user.suspended_reason = payload.reason
        await AuditEventService(db_session).record_event(
            audit_context=build_audit_context_from_request(
                actor_user_id=actor.user.id, request=request
            ),
            category=AuditCategory.PLATFORM,
            action=AuditAction.USER_SUSPENDED,
            target_type=AuditTargetType.USER,
            target_id=user.id,
            reason=payload.reason,
        )
    await db_session.refresh(user)
    return PlatformUserResponse.model_validate(user)


@router.post("/{user_id}/restore", response_model=PlatformUserResponse)
async def restore_platform_user(
    user_id: UUID,
    payload: ReasonRequest,
    actor: Annotated[
        object, Depends(require_platform_permission(PlatformPermission.USERS_RESTORE))
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformUserResponse:
    user = await db_session.get(User, user_id)
    if user is None:
        raise NotFoundError(detail="User not found")
    if user.status == UserStatus.ACTIVE:
        raise ConflictError(detail="User already active")
    async with db_session.begin():
        user.status = UserStatus.ACTIVE
        user.suspended_at = None
        user.suspended_reason = None
        await AuditEventService(db_session).record_event(
            audit_context=build_audit_context_from_request(
                actor_user_id=actor.user.id, request=request
            ),
            category=AuditCategory.PLATFORM,
            action=AuditAction.USER_RESTORED,
            target_type=AuditTargetType.USER,
            target_id=user.id,
            reason=payload.reason,
        )
    await db_session.refresh(user)
    return PlatformUserResponse.model_validate(user)
