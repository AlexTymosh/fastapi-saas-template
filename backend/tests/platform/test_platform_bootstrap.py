import pytest

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.commands.create_platform_admin import create_platform_admin_by_email
from app.core.db import get_session_factory
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async


def _seed_user(
    email: str, external_auth_id: str, status: UserStatus = UserStatus.ACTIVE
):
    async def _run():
        async with get_session_factory()() as session:
            async with session.begin():
                user = User(
                    external_auth_id=external_auth_id, email=email, status=status
                )
                session.add(user)
            return user

    return run_async(_run())


def test_create_platform_admin_cases(monkeypatch, migrated_database_url) -> None:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)

    with pytest.raises(NotFoundError):
        run_async(create_platform_admin_by_email("missing@example.com"))

    _seed_user("suspended@example.com", "kc-susp", UserStatus.SUSPENDED)
    with pytest.raises(ConflictError):
        run_async(create_platform_admin_by_email("suspended@example.com"))

    _seed_user("admin@example.com", "kc-admin")
    run_async(create_platform_admin_by_email("admin@example.com"))
    run_async(create_platform_admin_by_email("admin@example.com"))

    async def _seed_existing_conflicts():
        async with get_session_factory()() as session:
            async with session.begin():
                user = User(
                    external_auth_id="kc-support",
                    email="support@example.com",
                    status=UserStatus.ACTIVE,
                )
                session.add(user)
                await session.flush()
                session.add(
                    PlatformStaff(
                        user_id=user.id,
                        role=PlatformStaffRole.SUPPORT_AGENT.value,
                        status=PlatformStaffStatus.ACTIVE.value,
                    )
                )

                user2 = User(
                    external_auth_id="kc-suspended-staff",
                    email="suspended-staff@example.com",
                    status=UserStatus.ACTIVE,
                )
                session.add(user2)
                await session.flush()
                session.add(
                    PlatformStaff(
                        user_id=user2.id,
                        role=PlatformStaffRole.PLATFORM_ADMIN.value,
                        status=PlatformStaffStatus.SUSPENDED.value,
                    )
                )

    run_async(_seed_existing_conflicts())

    with pytest.raises(ConflictError):
        run_async(create_platform_admin_by_email("support@example.com"))
    with pytest.raises(ConflictError):
        run_async(create_platform_admin_by_email("suspended-staff@example.com"))

    async def _verify():
        async with get_session_factory()() as session:
            staff_rows = (
                await session.execute(
                    PlatformStaff.__table__.select().where(
                        PlatformStaff.role == PlatformStaffRole.PLATFORM_ADMIN.value
                    )
                )
            ).all()
            assert len(staff_rows) == 2
            audit = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.PLATFORM_STAFF_CREATED.value
                    )
                )
            ).all()
            assert len(audit) >= 1

    run_async(_verify())
