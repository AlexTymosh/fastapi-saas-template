import pytest

from app.commands.create_platform_admin import _run
from app.core.db import get_session_factory
from app.core.errors.exceptions import NotFoundError
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async


def test_create_platform_admin_fails_for_missing_user(
    monkeypatch, migrated_database_url
) -> None:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    with pytest.raises(NotFoundError):
        run_async(_run("missing@example.com"))


def test_create_platform_admin_success(monkeypatch, migrated_database_url) -> None:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)

    async def _seed():
        async with get_session_factory()() as session:
            async with session.begin():
                user = User(
                    external_auth_id="kc-bootstrap",
                    email="bootstrap@example.com",
                    status=UserStatus.ACTIVE,
                )
                session.add(user)

    run_async(_seed())
    run_async(_run("bootstrap@example.com"))

    async def _verify():
        async with get_session_factory()() as session:
            staff = (await session.execute(PlatformStaff.__table__.select())).first()
            assert staff is not None
            row = staff._mapping
            assert row["role"] == PlatformStaffRole.PLATFORM_ADMIN.value
            assert row["status"] == PlatformStaffStatus.ACTIVE.value

    run_async(_verify())
