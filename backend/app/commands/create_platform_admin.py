from __future__ import annotations

import argparse
import asyncio

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.db import get_session_factory
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.repositories.users import UserRepository


async def _run(email: str) -> None:
    async with get_session_factory()() as session:
        async with session.begin():
            user = await UserRepository(session).get_by_email(email)
            if user is None:
                raise NotFoundError(detail=f"User with email {email} not found")
            if user.status == UserStatus.SUSPENDED:
                raise ConflictError(detail="User is suspended")
            repo = PlatformStaffRepository(session)
            existing = await repo.get_by_user_id(user.id)
            if existing is not None:
                if (
                    existing.role == PlatformStaffRole.PLATFORM_ADMIN.value
                    and existing.status == PlatformStaffStatus.ACTIVE.value
                ):
                    return
                raise ConflictError(
                    detail="Platform staff record exists; manage it explicitly"
                )
            staff = await repo.create_staff(
                user_id=user.id, role=PlatformStaffRole.PLATFORM_ADMIN.value
            )
            await AuditEventService(session).record_event(
                audit_context=AuditContext(actor_user_id=None),
                category=AuditCategory.PLATFORM,
                action=AuditAction.PLATFORM_STAFF_CREATED,
                target_type=AuditTargetType.PLATFORM_STAFF,
                target_id=staff.id,
                reason="bootstrap platform admin",
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.email))


if __name__ == "__main__":
    main()
