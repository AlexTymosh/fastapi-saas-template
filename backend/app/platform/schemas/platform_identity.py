from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.core.platform import PlatformActor, PlatformPermission
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.users.models.user import UserStatus


class PlatformIdentityResponse(BaseModel):
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
    created_at: datetime
    updated_at: datetime
    staff_created_at: datetime
    staff_updated_at: datetime

    @classmethod
    def from_actor(cls, actor: PlatformActor) -> PlatformIdentityResponse:
        return cls(
            user_id=actor.user.id,
            staff_id=actor.staff.id,
            role=PlatformStaffRole(actor.staff.role),
            staff_status=PlatformStaffStatus(actor.staff.status),
            permissions=sorted(actor.permissions, key=str),
            email=actor.user.email,
            email_verified=actor.user.email_verified,
            first_name=actor.user.first_name,
            last_name=actor.user.last_name,
            user_status=UserStatus(actor.user.status),
            created_at=actor.user.created_at,
            updated_at=actor.user.updated_at,
            staff_created_at=actor.staff.created_at,
            staff_updated_at=actor.staff.updated_at,
        )
