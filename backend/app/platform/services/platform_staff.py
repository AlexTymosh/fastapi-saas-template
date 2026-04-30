from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform import PlatformActor
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService


class PlatformStaffService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PlatformStaffRepository(session)

    async def list_staff(self, *, limit: int, offset: int):
        return await self.repository.list_staff(limit=limit, offset=offset)

    async def create_platform_staff(
        self,
        *,
        user_id: UUID,
        role: PlatformStaffRole,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ):
        existing_user = await UserService(self.session).get_user_by_id(user_id)
        if existing_user.status != UserStatus.ACTIVE:
            raise ConflictError(detail="User must be active")
        existing_staff = await self.repository.get_by_user_id(user_id)
        if existing_staff is not None:
            raise ConflictError(detail="Platform staff record already exists")
        staff = await self.repository.create_staff(
            user_id=user_id, role=role.value, created_by_user_id=actor.user.id
        )
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.PLATFORM_STAFF_CREATED,
            target_type=AuditTargetType.PLATFORM_STAFF,
            target_id=staff.id,
            reason=reason,
            metadata_json={"user_id": str(user_id), "role": role.value},
        )
        return staff

    async def update_staff_role(
        self,
        *,
        staff_id: UUID,
        role: PlatformStaffRole,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ):
        staff = await self._get_staff(staff_id)
        if staff.status != PlatformStaffStatus.ACTIVE.value:
            raise ConflictError(detail="Only active staff role can be changed")
        if staff.role == role.value:
            raise ConflictError(detail="Role is already set")
        if (
            actor.user.id == staff.user_id
            and staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
        ):
            raise ConflictError(detail="Platform admin cannot demote own role")
        if (
            staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
            and role != PlatformStaffRole.PLATFORM_ADMIN
            and await self.repository.count_active_platform_admins() <= 1
        ):
            raise ConflictError(detail="Cannot demote last active platform admin")
        old_role = staff.role
        staff = await self.repository.update_role(staff=staff, role=role.value)
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.PLATFORM_STAFF_ROLE_CHANGED,
            target_type=AuditTargetType.PLATFORM_STAFF,
            target_id=staff.id,
            reason=reason,
            metadata_json={
                "old_role": old_role,
                "new_role": role.value,
                "target_user_id": str(staff.user_id),
            },
        )
        return staff

    async def suspend_staff(
        self,
        *,
        staff_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ):
        staff = await self._get_staff(staff_id)
        if staff.status != PlatformStaffStatus.ACTIVE.value:
            raise ConflictError(detail="Platform staff already suspended")
        if actor.user.id == staff.user_id:
            raise ConflictError(detail="Platform actor cannot suspend own staff record")
        if (
            staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
            and await self.repository.count_active_platform_admins() <= 1
        ):
            raise ConflictError(detail="Cannot suspend last active platform admin")
        staff = await self.repository.suspend_staff(staff=staff, reason=reason)
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.PLATFORM_STAFF_SUSPENDED,
            target_type=AuditTargetType.PLATFORM_STAFF,
            target_id=staff.id,
            reason=reason,
            metadata_json={"target_user_id": str(staff.user_id), "role": staff.role},
        )
        return staff

    async def restore_staff(
        self, *, staff_id: UUID, reason: str, audit_context: AuditContext
    ):
        staff = await self._get_staff(staff_id)
        if staff.status != PlatformStaffStatus.SUSPENDED.value:
            raise ConflictError(detail="Platform staff already active")
        staff = await self.repository.restore_staff(staff=staff)
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.PLATFORM_STAFF_RESTORED,
            target_type=AuditTargetType.PLATFORM_STAFF,
            target_id=staff.id,
            reason=reason,
            metadata_json={"target_user_id": str(staff.user_id), "role": staff.role},
        )
        return staff

    async def _get_staff(self, staff_id: UUID):
        staff = await self.repository.get_by_id(staff_id)
        if staff is None:
            raise NotFoundError(detail="Platform staff not found")
        return staff
