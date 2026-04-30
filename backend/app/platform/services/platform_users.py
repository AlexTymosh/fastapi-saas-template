from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform.actors import PlatformActor
from app.users.models.user import User, UserStatus


class PlatformUsersService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_users(self, limit: int, offset: int):
        rows = (
            (await self.session.execute(select(User).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        total = (
            await self.session.execute(select(func.count()).select_from(User))
        ).scalar_one()
        return rows, total

    async def get_user(self, user_id: UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError(detail="User not found")
        return user

    async def suspend_user(
        self, user_id: UUID, actor: PlatformActor, reason: str, audit_context
    ):
        async def _op():
            user = await self.get_user(user_id)
            if user.id == actor.user.id:
                raise ConflictError(detail="Platform actor cannot suspend own account")
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
            return user

        if self.session.in_transaction():
            return await _op()
        async with self.session.begin():
            return await _op()

    async def restore_user(
        self, user_id: UUID, actor: PlatformActor, reason: str, audit_context
    ):
        async def _op():
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
            return user

        if self.session.in_transaction():
            return await _op()
        async with self.session.begin():
            return await _op()
