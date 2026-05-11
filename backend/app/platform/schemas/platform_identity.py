from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.core.platform.permissions import PlatformPermission
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.users.models.user import UserStatus


class PlatformIdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    staff_id: UUID
    role: PlatformStaffRole
    staff_status: PlatformStaffStatus
    permissions: list[PlatformPermission]
    email: EmailStr | None
    email_verified: bool
    first_name: str | None
    last_name: str | None
    user_status: UserStatus
    user_created_at: datetime
    user_updated_at: datetime
    staff_created_at: datetime
    staff_updated_at: datetime
