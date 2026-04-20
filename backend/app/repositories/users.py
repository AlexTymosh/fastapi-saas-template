from __future__ import annotations

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

    async def create(
        self,
        *,
        external_auth_id: str,
        email: str | None,
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
        return user

    async def update_profile_fields(
        self,
        user: User,
        *,
        email: str | None,
        email_verified: bool,
        first_name: str | None,
        last_name: str | None,
        onboarding_completed: bool | None = None,
    ) -> User:
        user.email = email
        user.email_verified = email_verified
        user.first_name = first_name
        user.last_name = last_name

        if onboarding_completed is not None:
            user.onboarding_completed = onboarding_completed

        await self.session.flush()
        return user

    async def user_has_any_organisation(self, user_id) -> bool:
        from app.memberships.models.membership import Membership

        stmt = select(Membership.id).where(Membership.user_id == user_id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
