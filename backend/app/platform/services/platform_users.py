from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform.actors import PlatformActor
from app.users.models.user import User, UserStatus


class PlatformUsersService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_users(self, *, limit: int, offset: int) -> tuple[list[User], int]:
        rows = (
            (await self.session.execute(select(User).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        total = (
            await self.session.execute(select(func.count()).select_from(User))
        ).scalar_one()
        return list(rows), int(total)

    async def get_user(self, user_id: UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError(detail="User not found")
        return user

    async def _run_write(self, operation: Callable[[], Awaitable[User]]) -> User:
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

    async def suspend_user(
        self,
        *,
        user_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> User:
        return await self._run_write(
            lambda: self._suspend_user(
                user_id=user_id, actor=actor, reason=reason, audit_context=audit_context
            )
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
            raise ConflictError(detail="User already suspended")
        user.status = UserStatus.SUSPENDED
        user.suspended_at = datetime.now(UTC)
        user.suspended_reason = reason
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.USER_SUSPENDED,
            target_type=AuditTargetType.USER,
            target_id=user.id,
            reason=reason,
        )
        await self.session.flush()
        return user

    async def restore_user(
        self,
        *,
        user_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> User:
        return await self._run_write(
            lambda: self._restore_user(
                user_id=user_id, actor=actor, reason=reason, audit_context=audit_context
            )
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
            raise ConflictError(detail="User already active")
        user.status = UserStatus.ACTIVE
        user.suspended_at = None
        user.suspended_reason = None
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.USER_RESTORED,
            target_type=AuditTargetType.USER,
            target_id=user.id,
            reason=reason,
        )
        await self.session.flush()
        return user
