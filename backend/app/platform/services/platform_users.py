from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.users.models.user import UserStatus
from app.users.repositories.users import UserRepository


class PlatformUsersService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def suspend(self, *, user_id: UUID, reason: str, audit_context: AuditContext):
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(detail="User not found")
        if user.status == UserStatus.SUSPENDED.value:
            raise ConflictError(detail="User already suspended")
        user.status = UserStatus.SUSPENDED.value
        user.suspended_at = datetime.now(UTC)
        user.suspended_reason = reason.strip()
        await AuditEventService(self.session).record_event(audit_context=audit_context, category=AuditCategory.PLATFORM, action=AuditAction.USER_SUSPENDED, target_type=AuditTargetType.USER, target_id=user.id, reason=reason.strip())
        await self.session.flush()
        return user
