from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)


class PlatformStaffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: UUID) -> PlatformStaff | None:
        result = await self.session.execute(
            select(PlatformStaff).where(PlatformStaff.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, staff_id: UUID) -> PlatformStaff | None:
        result = await self.session.execute(
            select(PlatformStaff).where(PlatformStaff.id == staff_id)
        )
        return result.scalar_one_or_none()

    async def list_staff(
        self, *, limit: int, offset: int
    ) -> tuple[list[PlatformStaff], int]:
        result = await self.session.execute(
            select(PlatformStaff)
            .order_by(PlatformStaff.created_at.desc(), PlatformStaff.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = (
            await self.session.execute(select(func.count()).select_from(PlatformStaff))
        ).scalar_one()
        return list(result.scalars().all()), int(total)

    async def create_staff(
        self, *, user_id: UUID, role: str, created_by_user_id: UUID | None = None
    ) -> PlatformStaff:
        staff = PlatformStaff(
            user_id=user_id,
            role=role,
            status=PlatformStaffStatus.ACTIVE.value,
            created_by_user_id=created_by_user_id,
        )
        self.session.add(staff)
        await self.session.flush()
        await self.session.refresh(staff)
        return staff

    async def update_role(
        self, *, staff: PlatformStaff, role: PlatformStaffRole
    ) -> PlatformStaff:
        staff.role = role.value
        await self.session.flush()
        await self.session.refresh(staff)
        return staff

    async def suspend(self, *, staff: PlatformStaff, reason: str) -> PlatformStaff:
        staff.status = PlatformStaffStatus.SUSPENDED.value
        staff.suspended_at = datetime.now(UTC)
        staff.suspended_reason = reason
        await self.session.flush()
        await self.session.refresh(staff)
        return staff

    async def restore(self, *, staff: PlatformStaff) -> PlatformStaff:
        staff.status = PlatformStaffStatus.ACTIVE.value
        staff.suspended_at = None
        staff.suspended_reason = None
        await self.session.flush()
        await self.session.refresh(staff)
        return staff

    async def count_active_platform_admins(self) -> int:
        count = (
            await self.session.execute(
                select(func.count())
                .select_from(PlatformStaff)
                .where(
                    PlatformStaff.role == PlatformStaffRole.PLATFORM_ADMIN.value,
                    PlatformStaff.status == PlatformStaffStatus.ACTIVE.value,
                )
            )
        ).scalar_one()
        return int(count)
