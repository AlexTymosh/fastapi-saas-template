from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.domain_guards.guards import ensure_user_active
from app.users.models.user import User
from app.users.repositories.users import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)

    async def get_or_create_current_user(
        self, identity: AuthenticatedPrincipal
    ) -> User:
        user = await self.user_repository.get_by_external_auth_id(
            identity.external_auth_id
        )
        if user is None:
            try:
                async with self.session.begin_nested():
                    return await self.user_repository.create(
                        external_auth_id=identity.external_auth_id,
                        email=identity.email,
                        email_verified=identity.email_verified,
                        first_name=identity.first_name,
                        last_name=identity.last_name,
                    )
            except IntegrityError as exc:
                existing = await self.user_repository.get_by_external_auth_id(
                    identity.external_auth_id
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

    async def provision_current_user(self, identity: AuthenticatedPrincipal) -> User:
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

    async def get_me(self, identity: AuthenticatedPrincipal) -> User:
        return await self.provision_current_user(identity)

    async def get_user_by_id(self, user_id: UUID) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError(detail="User not found")
        return user

    async def ensure_user_is_active(self, user: User) -> None:
        ensure_user_active(user)
