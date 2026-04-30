from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db.session import get_db_session
from app.core.errors.exceptions import ForbiddenError
from app.core.platform.actors import PlatformActor
from app.core.platform.permissions import ROLE_PERMISSIONS, PlatformPermission, PlatformRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService

DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def require_platform_permission(permission: PlatformPermission):
    async def _dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated_principal)],
        session: DbSessionDep,
    ) -> PlatformActor:
        user = await UserService(session).provision_current_user(principal)
        if user.status != UserStatus.ACTIVE.value:
            raise ForbiddenError(detail="User is suspended")
        staff = await PlatformStaffRepository(session).get_by_user_id(user.id)
        if staff is None or staff.status != PlatformStaffStatus.ACTIVE.value:
            raise ForbiddenError(detail="Platform access denied")
        role = PlatformRole(staff.role)
        permissions = ROLE_PERMISSIONS[role]
        if permission not in permissions:
            raise ForbiddenError(detail="Missing platform permission")
        return PlatformActor(user=user, staff=staff, permissions=permissions)

    return _dependency
