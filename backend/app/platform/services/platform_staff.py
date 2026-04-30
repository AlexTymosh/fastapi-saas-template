from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import ConflictError
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository


class PlatformStaffService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PlatformStaffRepository(session)

    async def get_by_user_id(self, user_id: UUID):
        return await self.repository.get_by_user_id(user_id)

    async def create_platform_staff(
        self, *, user_id: UUID, role: str, created_by_user_id: UUID | None = None
    ):
        return await self._run_write(
            lambda: self._create_platform_staff(
                user_id=user_id, role=role, created_by_user_id=created_by_user_id
            )
        )

    async def _create_platform_staff(
        self, *, user_id: UUID, role: str, created_by_user_id: UUID | None = None
    ):
        existing = await self.repository.get_by_user_id(user_id)
        if existing is not None:
            if (
                existing.role == PlatformStaffRole.PLATFORM_ADMIN.value
                and existing.status == PlatformStaffStatus.ACTIVE.value
            ):
                return existing
            raise ConflictError(
                detail="Platform staff record exists; manage it explicitly"
            )
        return await self.repository.create_staff(
            user_id=user_id, role=role, created_by_user_id=created_by_user_id
        )

    async def _run_write(self, operation):
        if self.session.in_transaction():
            try:
                result = await operation()
                await self.session.commit()
                return result
            except Exception:
                await self.session.rollback()
                raise
        async with self.session.begin():
            return await operation()
