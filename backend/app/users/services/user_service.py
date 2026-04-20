from __future__ import annotations

from app.core.auth import AuthenticatedIdentity
from app.memberships.repositories.membership_repository import MembershipRepository
from app.users.models.user import User
from app.users.repositories.user_repository import UserRepository


class UserService:
    def __init__(
        self,
        user_repository: UserRepository,
        membership_repository: MembershipRepository,
    ) -> None:
        self.user_repository = user_repository
        self.membership_repository = membership_repository

    async def get_or_create_current_user(self, identity: AuthenticatedIdentity) -> User:
        user = await self.user_repository.get_by_external_auth_id(identity.sub)

        if user is None:
            return await self.user_repository.create(
                external_auth_id=identity.sub,
                email=identity.email,
                email_verified=identity.email_verified,
                first_name=identity.given_name,
                last_name=identity.family_name,
            )

        requires_update = any(
            (
                user.email != identity.email,
                user.email_verified != identity.email_verified,
                user.first_name != identity.given_name,
                user.last_name != identity.family_name,
            )
        )
        if requires_update:
            await self.user_repository.update_profile_fields(
                user,
                email=identity.email,
                email_verified=identity.email_verified,
                first_name=identity.given_name,
                last_name=identity.family_name,
            )

        return user

    async def get_me(self, identity: AuthenticatedIdentity) -> tuple[User, bool]:
        user = await self.get_or_create_current_user(identity)
        has_any_organisation = (
            await self.membership_repository.user_has_any_organisation(user.id)
        )
        return user, has_any_organisation
