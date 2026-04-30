from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.models.platform_staff import PlatformStaff


class PlatformStaffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: UUID) -> PlatformStaff | None:
        return (await self.session.execute(select(PlatformStaff).where(PlatformStaff.user_id == user_id))).scalar_one_or_none()

    async def get_by_id(self, staff_id: UUID) -> PlatformStaff | None:
        return (await self.session.execute(select(PlatformStaff).where(PlatformStaff.id == staff_id))).scalar_one_or_none()

    async def list_staff(self, *, limit: int = 50, offset: int = 0) -> list[PlatformStaff]:
        return list((await self.session.execute(select(PlatformStaff).offset(offset).limit(limit))).scalars())

    async def create_staff(self, *, user_id: UUID, role: str, created_by_user_id: UUID | None = None) -> PlatformStaff:
        staff = PlatformStaff(user_id=user_id, role=role, status="active", created_by_user_id=created_by_user_id)
        self.session.add(staff)
        await self.session.flush()
        await self.session.refresh(staff)
        return staff
