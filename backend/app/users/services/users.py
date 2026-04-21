from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedIdentity
from app.core.errors.exceptions import ConflictError
from app.users.models.user import User
from app.users.repositories.users import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
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
                existing = await self.user_repository.get_by_external_auth_id(
                    identity.sub
                )
                if existing is not None:
                    return existing
                raise ConflictError(
                    detail="Unable to provision local user projection"
                ) from exc

        needs_update = any(
            [
                user.email != identity.email,
                user.email_verified != identity.email_verified,
                user.first_name != identity.first_name,
                user.last_name != identity.last_name,
            ]
        )
        if needs_update:
            try:
                return await self.user_repository.update_profile_fields(
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

    async def provision_current_user(self, identity: AuthenticatedIdentity) -> User:
        """Persist JIT user projection changes with explicit transaction boundaries."""
        if self.session.in_transaction():
            return await self.get_or_create_current_user(identity=identity)

        async with self.session.begin():
            return await self.get_or_create_current_user(identity=identity)

    async def mark_onboarding_completed(self, user: User) -> User:
        if user.onboarding_completed:
            return user

        return await self.user_repository.update_onboarding_completed(
            user=user,
            onboarding_completed=True,
        )

    async def get_me(self, identity: AuthenticatedIdentity) -> User:
        return await self.provision_current_user(identity)
