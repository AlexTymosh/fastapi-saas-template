from __future__ import annotations

import inspect

import pytest
from sqlalchemy import func, select

import app.commands.make_platform_admin as make_platform_admin_module
from app.audit.models.audit_event import AuditAction, AuditEvent
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
                session.add(
                    PlatformStaff(user_id=user_id, role=role.value, status=status.value)
                )

    run_async(_run())


def test_make_platform_admin_creates_platform_admin_for_existing_active_user(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    active = _seed_user("bootstrap-active@example.com")

    result = run_async(make_platform_admin(active.email))

    assert result.status == MakePlatformAdminStatus.GRANTED
    assert result.email == active.email

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


def test_make_platform_admin_is_idempotent_for_existing_active_platform_admin(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    active = _seed_user("bootstrap-idempotent@example.com")

    first = run_async(make_platform_admin(active.email))
    second = run_async(make_platform_admin(active.email))

    assert first.status == MakePlatformAdminStatus.GRANTED
    assert second.status == MakePlatformAdminStatus.ALREADY_ACTIVE

    async def _verify():
        async with get_session_factory()() as session:
            staff_count = (
                await session.execute(
                    select(func.count())
                    .select_from(PlatformStaff)
                    .where(PlatformStaff.user_id == active.id)
                )
            ).scalar_one()
            assert staff_count == 1

    run_async(_verify())


def test_make_platform_admin_fails_when_user_does_not_exist(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)

    with pytest.raises(NotFoundError):
        run_async(make_platform_admin("missing@example.com"))

    async def _verify():
        async with get_session_factory()() as session:
            user_count = (
                await session.execute(select(func.count()).select_from(User))
            ).scalar_one()
            assert user_count == 0

    run_async(_verify())


def test_make_platform_admin_fails_when_user_is_suspended(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    suspended = _seed_user("bootstrap-suspended@example.com", UserStatus.SUSPENDED)

    with pytest.raises(ConflictError):
        run_async(make_platform_admin(suspended.email))


def test_make_platform_admin_fails_on_conflicting_platform_staff_role(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    staff_user = _seed_user("bootstrap-support@example.com")
    _seed_staff(
        staff_user.id,
        PlatformStaffRole.SUPPORT_AGENT,
        PlatformStaffStatus.ACTIVE,
    )

    with pytest.raises(ConflictError):
        run_async(make_platform_admin(staff_user.email))


def test_make_platform_admin_fails_on_suspended_platform_admin_record(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    staff_user = _seed_user("bootstrap-suspended-staff@example.com")
    _seed_staff(
        staff_user.id,
        PlatformStaffRole.PLATFORM_ADMIN,
        PlatformStaffStatus.SUSPENDED,
    )

    with pytest.raises(ConflictError):
        run_async(make_platform_admin(staff_user.email))


def test_make_platform_admin_does_not_create_tenant_membership_or_user_implicitly(
    monkeypatch, migrated_database_url
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    active = _seed_user("bootstrap-no-membership@example.com")

    run_async(make_platform_admin(active.email))

    async def _verify():
        async with get_session_factory()() as session:
            membership_count = (
                await session.execute(select(func.count()).select_from(Membership))
            ).scalar_one()
            user_count = (
                await session.execute(select(func.count()).select_from(User))
            ).scalar_one()
            assert membership_count == 0
            assert user_count == 1

    run_async(_verify())


def test_make_platform_admin_does_not_inspect_jwt_or_idp_roles():
    source = inspect.getsource(make_platform_admin_module)

    assert "realm_access" not in source
    assert "resource_access" not in source
    assert "jwt" not in source.lower()
    assert "keycloak" not in source.lower()
