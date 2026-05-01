from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.exceptions import ForbiddenError
from app.core.platform.actors import PlatformActor
from app.core.platform.permissions import (
    ROLE_PERMISSIONS,
    PlatformPermission,
    PlatformRole,
)
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService


@dataclass(frozen=True)
class PlatformWriteContext:
    session: AsyncSession
    actor: PlatformActor


async def resolve_platform_actor(
    *,
    identity: AuthenticatedPrincipal,
    session: AsyncSession,
    required_permission: PlatformPermission,
) -> PlatformActor:
    user = await UserService(session).get_current_user_projection(identity)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ForbiddenError(detail="Platform access denied")
    staff = await PlatformStaffRepository(session).get_by_user_id(user.id)
    if staff is None or staff.status != PlatformStaffStatus.ACTIVE.value:
        raise ForbiddenError(detail="Platform access denied")
    try:
        role = PlatformRole(staff.role)
    except ValueError:
        raise ForbiddenError(detail="Platform access denied") from None
    role_permissions = ROLE_PERMISSIONS.get(role, frozenset())
    if required_permission not in role_permissions:
        raise ForbiddenError(detail="Platform access denied")
    return PlatformActor(user=user, staff=staff, permissions=role_permissions)


def require_platform_write_context(
    permission: PlatformPermission,
) -> Callable[..., AsyncIterator[PlatformWriteContext]]:
    async def dependency(
        identity: Annotated[
            AuthenticatedPrincipal, Depends(require_authenticated_principal)
        ],
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> AsyncIterator[PlatformWriteContext]:
        async with db_session.begin():
            actor = await resolve_platform_actor(
                identity=identity,
                session=db_session,
                required_permission=permission,
            )
            yield PlatformWriteContext(session=db_session, actor=actor)

    return dependency
