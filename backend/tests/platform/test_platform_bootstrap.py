from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.commands.create_platform_admin import create_platform_admin_by_email
from app.commands.make_platform_admin import (
    MakePlatformAdminStatus,
    make_platform_admin,
)
from app.core.db import get_session_factory
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.memberships.models.membership import Membership
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security, pytest.mark.authz, pytest.mark.audit]


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
                staff = PlatformStaff(
                    user_id=user_id,
                    role=role.value,
                    status=status.value,
                )
                session.add(staff)
            return staff

    return run_async(_run())


def _staff_rows_for_user(user_id):
    async def _run():
        async with get_session_factory()() as session:
            return list(
                (
                    await session.execute(
                        select(PlatformStaff).where(PlatformStaff.user_id == user_id)
                    )
                ).scalars()
            )

    return run_async(_run())


def test_make_platform_admin_creates_platform_admin_for_existing_active_user(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    user = _seed_user("bootstrap-active@example.com")

    result = run_async(make_platform_admin(user.email))

    assert result.status == MakePlatformAdminStatus.GRANTED
    staff_rows = _staff_rows_for_user(user.id)
    assert len(staff_rows) == 1
    assert staff_rows[0].role == PlatformStaffRole.PLATFORM_ADMIN.value
    assert staff_rows[0].status == PlatformStaffStatus.ACTIVE.value

    async def _verify_audit_event():
        async with get_session_factory()() as session:
            event = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == AuditAction.PLATFORM_STAFF_CREATED.value,
                        AuditEvent.target_id == staff_rows[0].id,
                    )
                )
            ).scalar_one_or_none()
            assert event is not None

    run_async(_verify_audit_event())


def test_make_platform_admin_is_idempotent_for_active_platform_admin(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    user = _seed_user("bootstrap-idempotent@example.com")

    run_async(make_platform_admin(user.email))
    result = run_async(make_platform_admin(user.email))

    assert result.status == MakePlatformAdminStatus.ALREADY_ACTIVE
    assert len(_staff_rows_for_user(user.id)) == 1


def test_make_platform_admin_fails_when_user_does_not_exist(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)

    with pytest.raises(NotFoundError):
        run_async(make_platform_admin("missing@example.com"))


def test_make_platform_admin_fails_when_user_is_suspended(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    user = _seed_user("bootstrap-suspended@example.com", UserStatus.SUSPENDED)

    with pytest.raises(ConflictError):
        run_async(make_platform_admin(user.email))


def test_make_platform_admin_fails_on_conflicting_platform_staff_without_force(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    user = _seed_user("bootstrap-support@example.com")
    _seed_staff(user.id, PlatformStaffRole.SUPPORT_AGENT, PlatformStaffStatus.ACTIVE)

    with pytest.raises(ConflictError):
        run_async(make_platform_admin(user.email))


def test_make_platform_admin_force_promotes_existing_staff_and_is_idempotent(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    user = _seed_user("bootstrap-force@example.com")
    _seed_staff(
        user.id,
        PlatformStaffRole.COMPLIANCE_OFFICER,
        PlatformStaffStatus.ACTIVE,
    )

    result = run_async(make_platform_admin(user.email, force=True))
    idempotent_result = run_async(make_platform_admin(user.email, force=True))

    assert result.status == MakePlatformAdminStatus.GRANTED
    assert idempotent_result.status == MakePlatformAdminStatus.ALREADY_ACTIVE
    staff_rows = _staff_rows_for_user(user.id)
    assert len(staff_rows) == 1
    assert staff_rows[0].role == PlatformStaffRole.PLATFORM_ADMIN.value
    assert staff_rows[0].status == PlatformStaffStatus.ACTIVE.value


def test_make_platform_admin_does_not_create_user_or_tenant_membership(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    user = _seed_user("bootstrap-no-membership@example.com")

    run_async(make_platform_admin(user.email))

    async def _verify():
        async with get_session_factory()() as session:
            user_count = (
                await session.execute(select(func.count()).select_from(User))
            ).scalar_one()
            membership_count = (
                await session.execute(select(func.count()).select_from(Membership))
            ).scalar_one()
            assert user_count == 1
            assert membership_count == 0

    run_async(_verify())


def test_create_platform_admin_backward_compatible_alias(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    user = _seed_user("bootstrap-legacy-command@example.com")

    run_async(create_platform_admin_by_email(user.email))

    staff_rows = _staff_rows_for_user(user.id)
    assert len(staff_rows) == 1
    assert staff_rows[0].role == PlatformStaffRole.PLATFORM_ADMIN.value
