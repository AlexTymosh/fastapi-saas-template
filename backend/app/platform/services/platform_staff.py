from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import ConflictError
from app.core.platform.permissions import ROLE_PERMISSIONS, PlatformRole, PlatformStaffStatus
from app.platform.models.platform_staff import PlatformStaff
from app.platform.repositories.platform_staff import PlatformStaffRepository


class PlatformStaffService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PlatformStaffRepository(session)

    async def create_platform_staff(self, *, user_id: UUID, role: PlatformRole, created_by_user_id: UUID | None = None) -> PlatformStaff:
        return await self.repository.create_staff(user_id=user_id, role=role.value, created_by_user_id=created_by_user_id)

    async def suspend_platform_staff(self, staff: PlatformStaff, *, reason: str) -> PlatformStaff:
        if staff.status == PlatformStaffStatus.SUSPENDED.value:
            raise ConflictError(detail="Platform staff is already suspended")
        staff.status = PlatformStaffStatus.SUSPENDED.value
        staff.suspended_reason = reason
        staff.suspended_at = datetime.now(UTC)
        await self.session.flush()
        return staff

    async def restore_platform_staff(self, staff: PlatformStaff) -> PlatformStaff:
        if staff.status == PlatformStaffStatus.ACTIVE.value:
            raise ConflictError(detail="Platform staff is already active")
        staff.status = PlatformStaffStatus.ACTIVE.value
        staff.suspended_reason = None
        staff.suspended_at = None
        await self.session.flush()
        return staff

    def get_platform_actor_permissions(self, role: PlatformRole) -> frozenset:
        return ROLE_PERMISSIONS[role]
