from dataclasses import dataclass

from app.core.platform.permissions import PlatformPermission
from app.platform.models.platform_staff import PlatformStaff
from app.users.models.user import User


@dataclass(frozen=True)
class PlatformActor:
    user: User
    staff: PlatformStaff
    permissions: frozenset[PlatformPermission]
