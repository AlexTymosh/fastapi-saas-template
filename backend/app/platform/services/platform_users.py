from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform.actors import PlatformActor
from app.users.models.user import UserStatus
from app.users.repositories.users import UserRepository

if TYPE_CHECKING:
    from app.users.models.user import User


class PlatformUsersService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.audit_service = AuditEventService(session)

    async def list_users(
        self,
        *,
        limit: int,
        offset: int,
        status: UserStatus | None,
        q: str | None,
    ) -> tuple[list[User], int]:
        normalised_q = q.strip() if q is not None else None
        if normalised_q == "":
            normalised_q = None
        return await self.user_repository.list_paginated(
            limit=limit, offset=offset, status=status, q=normalised_q
        )

    async def list_limited_users(
        self,
        *,
        limit: int,
        offset: int,
        status: UserStatus | None,
        q: str | None,
    ) -> tuple[list[User], int]:
        normalised_q = q.strip() if q is not None else None
        if normalised_q == "":
            normalised_q = None
        return await self.user_repository.list_limited_paginated(
            limit=limit, offset=offset, status=status, q=normalised_q
        )

    async def get_user(self, user_id: UUID) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError(detail="User not found")
        return user

    async def suspend_user(
        self,
        *,
        user_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> User:
        return await self._suspend_user(
            user_id=user_id,
            actor=actor,
            reason=reason,
            audit_context=audit_context,
        )

    async def _suspend_user(
        self,
        *,
        user_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> User:
        if actor.user.id == user_id:
            raise ConflictError(detail="Platform actor cannot suspend own account")
        user = await self.get_user(user_id)
        if user.status == UserStatus.SUSPENDED:
            return user
        user = await self.user_repository.set_status(
            user,
            status=UserStatus.SUSPENDED,
            suspended_at=datetime.now(UTC),
            suspended_reason=reason,
        )
        await self.audit_service.record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.USER_SUSPENDED,
            target_type=AuditTargetType.USER,
            target_id=user.id,
            reason=reason,
        )
        return user

    async def restore_user(
        self,
        *,
        user_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> User:
        return await self._restore_user(
            user_id=user_id,
            actor=actor,
            reason=reason,
            audit_context=audit_context,
        )

    async def _restore_user(
        self,
        *,
        user_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> User:
        _ = actor
        user = await self.get_user(user_id)
        if user.status == UserStatus.ACTIVE:
            return user
        user = await self.user_repository.set_status(
            user,
            status=UserStatus.ACTIVE,
            suspended_at=None,
            suspended_reason=None,
        )
        await self.audit_service.record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.USER_RESTORED,
            target_type=AuditTargetType.USER,
            target_id=user.id,
            reason=reason,
        )
        return user
