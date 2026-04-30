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


def _seed_user(email: str, status: UserStatus = UserStatus.ACTIVE):
    async def _run():
        async with get_session_factory()() as session:
            async with session.begin():
                user = User(external_auth_id=f"kc-{email}", email=email, status=status)
                session.add(user)
            return user

    return run_async(_run())


def _seed_staff(user_id, role: PlatformStaffRole, status: PlatformStaffStatus):
    async def _run():
        async with get_session_factory()() as session:
            async with session.begin():
                session.add(
                    PlatformStaff(user_id=user_id, role=role.value, status=status.value)
                )

    run_async(_run())


def test_bootstrap_behaviour_matrix(monkeypatch, migrated_database_url):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)

    active = _seed_user("bootstrap-active@example.com")
    run_async(create_platform_admin_by_email(active.email))

    with pytest.raises(NotFoundError):
        run_async(create_platform_admin_by_email("missing@example.com"))

    suspended = _seed_user("bootstrap-suspended@example.com", UserStatus.SUSPENDED)
    with pytest.raises(ConflictError):
        run_async(create_platform_admin_by_email(suspended.email))

    run_async(create_platform_admin_by_email(active.email))

    different_role_user = _seed_user("bootstrap-support@example.com")
    _seed_staff(
        different_role_user.id,
        PlatformStaffRole.SUPPORT_AGENT,
        PlatformStaffStatus.ACTIVE,
    )
    with pytest.raises(ConflictError):
        run_async(create_platform_admin_by_email(different_role_user.email))

    suspended_staff_user = _seed_user("bootstrap-suspended-staff@example.com")
    _seed_staff(
        suspended_staff_user.id,
        PlatformStaffRole.PLATFORM_ADMIN,
        PlatformStaffStatus.SUSPENDED,
    )
    with pytest.raises(ConflictError):
        run_async(create_platform_admin_by_email(suspended_staff_user.email))

    async def _verify():
        async with get_session_factory()() as session:
            staff_rows = (
                await session.execute(
                    PlatformStaff.__table__.select().where(
                        PlatformStaff.user_id == active.id
                    )
                )
            ).all()
            assert len(staff_rows) == 1
            row = staff_rows[0]._mapping
            assert row["role"] == PlatformStaffRole.PLATFORM_ADMIN.value
            assert row["status"] == PlatformStaffStatus.ACTIVE.value

            event = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.PLATFORM_STAFF_CREATED.value,
                        AuditEvent.target_id == row["id"],
                    )
                )
            ).first()
            assert event is not None

    run_async(_verify())
