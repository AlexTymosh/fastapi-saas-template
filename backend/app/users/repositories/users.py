from __future__ import annotations

from uuid import UUID

from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models.user import User


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
