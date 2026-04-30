from __future__ import annotations

from collections.abc import Callable
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
    PlatformStaffStatus,
)
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService


def require_platform_permission(
    permission: PlatformPermission,
) -> Callable[..., PlatformActor]:
    async def dependency(
        identity: Annotated[
            AuthenticatedPrincipal, Depends(require_authenticated_principal)
        ],
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> PlatformActor:
        user = await UserService(db_session).provision_current_user(identity)
        if user.status != UserStatus.ACTIVE:
            raise ForbiddenError(detail="Platform access denied")
        staff = await PlatformStaffRepository(db_session).get_by_user_id(user.id)
        if staff is None or staff.status != PlatformStaffStatus.ACTIVE.value:
            raise ForbiddenError(detail="Platform access denied")
        role_permissions = ROLE_PERMISSIONS.get(staff.role, frozenset())
        if permission not in role_permissions:
            raise ForbiddenError(detail="Platform access denied")
        return PlatformActor(user=user, staff=staff, permissions=role_permissions)

    return dependency
