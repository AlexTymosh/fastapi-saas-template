from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors.openapi import COMMON_ERROR_RESPONSES, RATE_LIMIT_ERROR_RESPONSES
from app.core.platform import PlatformActor, require_platform_actor
from app.core.rate_limit import PLATFORM_READ_POLICY, rate_limit_dependency
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.schemas.platform_identity import PlatformIdentityResponse
from app.users.models.user import UserStatus

router = APIRouter(prefix="/platform", tags=["platform-identity"])


@router.get(
    "/me",
    response_model=PlatformIdentityResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def get_platform_identity(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    actor: Annotated[PlatformActor, Depends(require_platform_actor)],
) -> PlatformIdentityResponse:
    user = actor.user
    staff = actor.staff
    return PlatformIdentityResponse(
        user_id=user.id,
        staff_id=staff.id,
        role=PlatformStaffRole(staff.role),
        staff_status=PlatformStaffStatus(staff.status),
        permissions=sorted(actor.permissions, key=lambda permission: permission.value),
        email=user.email,
        email_verified=user.email_verified,
        first_name=user.first_name,
        last_name=user.last_name,
        user_status=UserStatus(user.status),
        user_created_at=user.created_at,
        user_updated_at=user.updated_at,
        staff_created_at=staff.created_at,
        staff_updated_at=staff.updated_at,
    )
