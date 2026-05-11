import pytest

from app.core.platform.permissions import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    PlatformRole,
)
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.auth, pytest.mark.authz]


def _seed_local_user(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    user_status: UserStatus = UserStatus.ACTIVE,
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


def _permissions(values: list[str]) -> set[str]:
    return set(values)


def test_platform_identity_unauthenticated_request_returns_401(client) -> None:
    response = client.get("/api/v1/platform/me")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_platform_identity_missing_local_user_projection_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    bundle = authenticated_client_factory(
        identity=identity_for("kc-missing-platform-me", "missing-me@example.com"),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform access denied"

    async def _assert_missing_user():
        async with migrated_session_factory() as session:
            user = await UserService(session).user_repository.get_by_external_auth_id(
                "kc-missing-platform-me"
            )
            assert user is None

    run_async(_assert_missing_user())


def test_platform_identity_suspended_local_user_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-suspended-user-me",
        email="suspended-user-me@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
        user_status=UserStatus.SUSPENDED,
    )[0]
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform access denied"


def test_platform_identity_missing_platform_staff_row_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _seed_local_user(
        migrated_session_factory,
        external_auth_id="kc-no-staff-me",
        email="no-staff-me@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform access denied"


def test_platform_identity_suspended_platform_staff_row_returns_403(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-suspended-staff-me",
        email="suspended-staff-me@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
        staff_status=PlatformStaffStatus.SUSPENDED,
    )[0]
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform access denied"


def test_platform_identity_platform_admin_returns_all_permissions(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user, staff = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-admin-me",
        email="admin-me@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
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
    assert payload["role"] == PlatformRole.PLATFORM_ADMIN.value
    assert payload["staff_status"] == PlatformStaffStatus.ACTIVE.value
    assert payload["email"] == user.email
    assert payload["email_verified"] is True
    assert payload["first_name"] == "Platform"
    assert payload["last_name"] == "Actor"
    assert payload["user_status"] == UserStatus.ACTIVE.value
    assert _permissions(payload["permissions"]) == {
        permission.value for permission in ALL_PERMISSIONS
    }


def test_platform_identity_support_agent_returns_only_support_permissions(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user, _staff = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-support-me",
        email="support-me@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == PlatformRole.SUPPORT_AGENT.value
    assert _permissions(payload["permissions"]) == {
        permission.value for permission in ROLE_PERMISSIONS[PlatformRole.SUPPORT_AGENT]
    }


def test_platform_identity_compliance_officer_returns_only_compliance_permissions(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user, _staff = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-compliance-me",
        email="compliance-me@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == PlatformRole.COMPLIANCE_OFFICER.value
    assert _permissions(payload["permissions"]) == {
        permission.value
        for permission in ROLE_PERMISSIONS[PlatformRole.COMPLIANCE_OFFICER]
    }


def test_platform_identity_response_does_not_expose_internal_fields(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user, _staff = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-safe-fields-me",
        email="safe-fields-me@example.com",
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
        "suspended_at",
        "suspended_reason",
        "created_by_user_id",
        "staff_suspended_at",
        "staff_suspended_reason",
    }
    assert forbidden_fields.isdisjoint(response.json())
