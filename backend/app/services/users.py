from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedIdentity
from app.repositories.memberships import MembershipRepository
from app.repositories.users import UserRepository
from app.users.models.user import User


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.user_repository = UserRepository(session)
        self.membership_repository = MembershipRepository(session)

    async def get_or_create_current_user(self, identity: AuthenticatedIdentity) -> User:
        user = await self.user_repository.get_by_external_auth_id(identity.sub)
        if user is None:
            return await self.user_repository.create(
                external_auth_id=identity.sub,
                email=identity.email,
                email_verified=identity.email_verified,
                first_name=identity.first_name,
                last_name=identity.last_name,
            )

        needs_update = any(
            [
                user.email != identity.email,
                user.email_verified != identity.email_verified,
                user.first_name != identity.first_name,
                user.last_name != identity.last_name,
            ]
        )
        if needs_update:
            await self.user_repository.update_profile_fields(
                user,
                email=identity.email,
                email_verified=identity.email_verified,
                first_name=identity.first_name,
                last_name=identity.last_name,
            )

        return user

    async def get_me(self, identity: AuthenticatedIdentity) -> tuple[User, bool]:
        user = await self.get_or_create_current_user(identity)
        has_org = await self.user_repository.user_has_any_organisation(user.id)
        return user, has_org
