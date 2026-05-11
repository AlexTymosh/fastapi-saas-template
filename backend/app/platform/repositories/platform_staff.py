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
        self,
        *,
        limit: int,
        offset: int,
        status: PlatformStaffStatus | None = None,
        role: PlatformStaffRole | None = None,
    ) -> tuple[list[PlatformStaff], int]:
        stmt = select(PlatformStaff)
        total_stmt = select(func.count()).select_from(PlatformStaff)
        conditions = []
        if status is not None:
            conditions.append(PlatformStaff.status == status.value)
        if role is not None:
            conditions.append(PlatformStaff.role == role.value)
        for condition in conditions:
            stmt = stmt.where(condition)
            total_stmt = total_stmt.where(condition)
        result = await self.session.execute(
            stmt.order_by(PlatformStaff.created_at.desc(), PlatformStaff.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
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

    async def promote_to_active_platform_admin(
        self, *, staff: PlatformStaff
    ) -> PlatformStaff:
        staff.role = PlatformStaffRole.PLATFORM_ADMIN.value
        staff.status = PlatformStaffStatus.ACTIVE.value
        staff.suspended_at = None
        staff.suspended_reason = None
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

    async def lock_active_platform_admins(self) -> list[PlatformStaff]:
        result = await self.session.execute(
            select(PlatformStaff)
            .where(
                PlatformStaff.role == PlatformStaffRole.PLATFORM_ADMIN.value,
                PlatformStaff.status == PlatformStaffStatus.ACTIVE.value,
            )
            .order_by(PlatformStaff.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

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
