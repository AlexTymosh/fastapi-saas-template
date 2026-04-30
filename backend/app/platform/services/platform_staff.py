from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import ConflictError
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository


class PlatformStaffService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = PlatformStaffRepository(session)

    async def get_by_user_id(self, user_id):
        return await self.repo.get_by_user_id(user_id)

    async def create_platform_staff(self, user_id, role, created_by_user_id=None):
        async def _create():
            existing = await self.repo.get_by_user_id(user_id)
            if existing is not None:
                if (
                    existing.role == role
                    and existing.status == PlatformStaffStatus.ACTIVE.value
                ):
                    return existing
                raise ConflictError(
                    detail="Platform staff record exists; manage it explicitly"
                )
            return await self.repo.create_staff(
                user_id=user_id, role=role, created_by_user_id=created_by_user_id
            )

        if self.session.in_transaction():
            return await _create()
        async with self.session.begin():
            return await _create()
