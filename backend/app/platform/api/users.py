from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.core.db.session import get_db_session
from app.core.platform.actors import PlatformActor
from app.core.platform.dependencies import require_platform_permission
from app.core.platform.permissions import PlatformPermission
from app.platform.schemas.platform_users import PlatformUserResponse, ReasonRequest
from app.platform.services.platform_users import PlatformUsersService
from app.users.models.user import User

router = APIRouter(tags=["platform-users"])
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/platform/users", response_model=list[PlatformUserResponse])
async def list_users(session: DbSessionDep, _: Annotated[PlatformActor, Depends(require_platform_permission(PlatformPermission.USERS_READ))]):
    return list((await session.execute(select(User).limit(50))).scalars())


@router.get("/platform/users/{user_id}", response_model=PlatformUserResponse)
async def get_user(user_id: UUID, session: DbSessionDep, _: Annotated[PlatformActor, Depends(require_platform_permission(PlatformPermission.USERS_READ))]):
    return await PlatformUsersService(session).users.get_by_id(user_id)

@router.post('/platform/users/{user_id}/suspend', response_model=PlatformUserResponse)
async def suspend_user(user_id: UUID, payload: ReasonRequest, session: DbSessionDep, actor: Annotated[PlatformActor, Depends(require_platform_permission(PlatformPermission.USERS_SUSPEND))]):
    async with session.begin():
        return await PlatformUsersService(session).suspend(user_id=user_id, reason=payload.reason.strip(), audit_context=AuditContext(actor_user_id=actor.user.id))
