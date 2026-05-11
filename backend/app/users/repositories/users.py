from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models.user import User, UserStatus


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_external_auth_id(self, external_auth_id: str) -> User | None:
        stmt = select(User).where(User.external_auth_id == external_auth_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        limit: int,
        offset: int,
        status: UserStatus | None = None,
        q: str | None = None,
    ) -> tuple[list[User], int]:
        stmt = select(User)
        total_stmt = select(func.count()).select_from(User)
        conditions = []
        if status is not None:
            conditions.append(User.status == status)
        if q:
            pattern = f"%{q.lower()}%"
            conditions.append(
                or_(
                    func.lower(User.email).like(pattern),
                    func.lower(User.first_name).like(pattern),
                    func.lower(User.last_name).like(pattern),
                )
            )
        for condition in conditions:
            stmt = stmt.where(condition)
            total_stmt = total_stmt.where(condition)
        stmt = (
            stmt.order_by(User.created_at.desc(), User.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        total_result = await self.session.execute(total_stmt)
        return list(result.scalars().all()), int(total_result.scalar_one())

    async def list_limited_paginated(
        self,
        *,
        limit: int,
        offset: int,
        status: UserStatus | None = None,
        q: str | None = None,
    ) -> tuple[list[User], int]:
        stmt = select(User)
        total_stmt = select(func.count()).select_from(User)
        conditions = []
        if status is not None:
            conditions.append(User.status == status)
        if q:
            pattern = f"%{q.lower()}%"
            conditions.append(
                or_(
                    func.lower(User.first_name).like(pattern),
                    func.lower(User.last_name).like(pattern),
                    func.lower(User.email).like(pattern),
                )
            )
        for condition in conditions:
            stmt = stmt.where(condition)
            total_stmt = total_stmt.where(condition)
        stmt = (
            stmt.order_by(User.created_at.desc(), User.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        total_result = await self.session.execute(total_stmt)
        return list(result.scalars().all()), int(total_result.scalar_one())

    async def create(
        self,
        *,
        external_auth_id: str,
        email: EmailStr | None,
        email_verified: bool,
        first_name: str | None,
        last_name: str | None,
    ) -> User:
        user = User(
            external_auth_id=external_auth_id,
            email=email,
            email_verified=email_verified,
            first_name=first_name,
            last_name=last_name,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update_profile_fields(
        self,
        user: User,
        *,
        email: EmailStr | None,
        email_verified: bool,
        first_name: str | None,
        last_name: str | None,
    ) -> User:
        user.email = email
        user.email_verified = email_verified
        user.first_name = first_name
        user.last_name = last_name
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update_onboarding_completed(
        self,
        *,
        user: User,
        onboarding_completed: bool,
    ) -> User:
        user.onboarding_completed = onboarding_completed
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def set_status(
        self,
        user: User,
        *,
        status: UserStatus,
        suspended_at: datetime | None,
        suspended_reason: str | None,
    ) -> User:
        user.status = status
        user.suspended_at = suspended_at
        user.suspended_reason = suspended_reason
        await self.session.flush()
        await self.session.refresh(user)
        return user
