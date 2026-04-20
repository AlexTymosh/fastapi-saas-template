from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedIdentity
from app.core.errors.exceptions import ConflictError
from app.users.models.user import User
from app.users.repositories.users import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.user_repository = UserRepository(session)

    async def get_or_create_current_user(self, identity: AuthenticatedIdentity) -> User:
        user = await self.user_repository.get_by_external_auth_id(identity.sub)
        if user is None:
            try:
                return await self.user_repository.create(
                    external_auth_id=identity.sub,
                    email=identity.email,
                    email_verified=identity.email_verified,
                    first_name=identity.first_name,
                    last_name=identity.last_name,
                )
            except IntegrityError as exc:
                raced_user = await self.user_repository.get_by_external_auth_id(
                    identity.sub
                )
                if raced_user is not None:
                    return raced_user
                raise ConflictError(detail="Failed to create user projection") from exc

        needs_update = any(
            (
                user.email != identity.email,
                user.email_verified != identity.email_verified,
                user.first_name != identity.first_name,
                user.last_name != identity.last_name,
            )
        )
        if needs_update:
            try:
                await self.user_repository.update_profile_fields(
                    user,
                    email=identity.email,
                    email_verified=identity.email_verified,
                    first_name=identity.first_name,
                    last_name=identity.last_name,
                )
            except IntegrityError as exc:
                raise ConflictError(
                    detail="User profile conflicts with existing data"
                ) from exc

        return user

    async def mark_onboarding_completed(self, user: User) -> User:
        if user.onboarding_completed:
            return user
        return await self.user_repository.update_onboarding_completed(
            user=user,
            onboarding_completed=True,
        )

    async def get_me(self, identity: AuthenticatedIdentity) -> User:
        return await self.get_or_create_current_user(identity)
