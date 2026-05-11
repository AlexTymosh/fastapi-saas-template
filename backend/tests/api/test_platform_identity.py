from __future__ import annotations

import pytest

from app.core.platform.permissions import ROLE_PERMISSIONS, PlatformRole
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


def _seed_user(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    status: UserStatus = UserStatus.ACTIVE,
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                user.status = status
                user.first_name = "Platform"
                user.last_name = "Actor"
                await session.flush()
            return user

    return run_async(_run())


def _seed_platform_staff(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    role: PlatformRole,
    user_status: UserStatus = UserStatus.ACTIVE,
    staff_status: PlatformStaffStatus = PlatformStaffStatus.ACTIVE,
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                user.status = user_status
                user.first_name = "Platform"
                user.last_name = "Actor"
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
                staff.status = staff_status.value
                await session.flush()
            return user, staff

    return run_async(_run())


def _permissions_for(role: PlatformRole) -> list[str]:
    return sorted(permission.value for permission in ROLE_PERMISSIONS[role])


def _assert_platform_access_denied(response) -> None:
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Platform access denied"


def test_platform_me_unauthenticated_request_returns_401(client_factory) -> None:
    with client_factory(database_url=None) as client:
        response = client.get("/api/v1/platform/me")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_platform_me_missing_local_user_projection_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    bundle = authenticated_client_factory(
        identity=identity_for("kc-platform-me-missing", "missing@example.com"),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    _assert_platform_access_denied(response)

    async def _assert_missing_user():
        async with migrated_session_factory() as session:
            user = await UserService(session).user_repository.get_by_external_auth_id(
                "kc-platform-me-missing"
            )
            assert user is None

    run_async(_assert_missing_user())


def test_platform_me_suspended_local_user_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-me-suspended-user",
        email="suspended-user@example.com",
        status=UserStatus.SUSPENDED,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    _assert_platform_access_denied(response)


def test_platform_me_missing_platform_staff_row_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-me-no-staff",
        email="no-staff@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    _assert_platform_access_denied(response)


def test_platform_me_suspended_platform_staff_row_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-me-suspended-staff",
        email="suspended-staff@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
        staff_status=PlatformStaffStatus.SUSPENDED,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    _assert_platform_access_denied(response)


@pytest.mark.parametrize(
    "role",
    [
        PlatformRole.PLATFORM_ADMIN,
        PlatformRole.SUPPORT_AGENT,
        PlatformRole.COMPLIANCE_OFFICER,
    ],
)
def test_platform_me_active_staff_returns_role_permissions_and_safe_profile(
    role: PlatformRole,
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    user, staff = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id=f"kc-platform-me-{role.value}",
        email=f"{role.value}@example.com",
        role=role,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email, roles=["untrusted"]),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == str(user.id)
    assert payload["staff_id"] == str(staff.id)
    assert payload["role"] == role.value
    assert payload["staff_status"] == PlatformStaffStatus.ACTIVE.value
    assert payload["permissions"] == _permissions_for(role)
    assert payload["email"] == user.email
    assert payload["email_verified"] is True
    assert payload["first_name"] == "Platform"
    assert payload["last_name"] == "Actor"
    assert payload["user_status"] == UserStatus.ACTIVE.value
    assert payload["user_created_at"] is not None
    assert payload["user_updated_at"] is not None
    assert payload["staff_created_at"] is not None
    assert payload["staff_updated_at"] is not None


def test_platform_me_response_does_not_expose_internal_fields(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-me-safe-fields",
        email="safe-fields@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 200
    forbidden_fields = {
        "external_auth_id",
        "onboarding_completed",
        "created_by_user_id",
        "suspended_at",
        "suspended_reason",
    }
    assert forbidden_fields.isdisjoint(response.json())
