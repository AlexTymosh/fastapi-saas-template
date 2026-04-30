from app.core.platform.permissions import PlatformRole
from app.organisations.services.organisations import OrganisationService
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import User, UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def _seed_staff(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    role: str,
    staff_status: str = "active",
    user_status: UserStatus = UserStatus.ACTIVE,
) -> User:
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                user.status = user_status
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id, role=role
                )
                staff.status = staff_status
            return user

    return run_async(_run())


def test_platform_permissions_matrix(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-susp-user",
        email="susp-user@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
        user_status=UserStatus.SUSPENDED,
    )
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-susp-staff",
        email="susp-staff@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
        staff_status="suspended",
    )
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-invalid-role",
        email="invalid-role@example.com",
        role="invalid_role",
    )
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-support",
        email="support@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-comp",
        email="comp@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER.value,
    )
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-admin",
        email="admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    assert (
        authenticated_client_factory(
            identity=identity_for("kc-susp-user", "susp-user@example.com"),
            database_url=migrated_database_url,
        )
        .client.get("/api/v1/platform/users")
        .status_code
        == 403
    )
    assert (
        authenticated_client_factory(
            identity=identity_for("kc-susp-staff", "susp-staff@example.com"),
            database_url=migrated_database_url,
        )
        .client.get("/api/v1/platform/users")
        .status_code
        == 403
    )
    assert (
        authenticated_client_factory(
            identity=identity_for("kc-invalid-role", "invalid-role@example.com"),
            database_url=migrated_database_url,
        )
        .client.get("/api/v1/platform/users")
        .status_code
        == 403
    )

    support = authenticated_client_factory(
        identity=identity_for("kc-support", "support@example.com"),
        database_url=migrated_database_url,
    )
    compliance = authenticated_client_factory(
        identity=identity_for("kc-comp", "comp@example.com"),
        database_url=migrated_database_url,
    )
    admin = authenticated_client_factory(
        identity=identity_for("kc-admin", "admin@example.com"),
        database_url=migrated_database_url,
    )

    assert (
        support.client.post(
            "/api/v1/platform/users/00000000-0000-0000-0000-000000000000/suspend",
            json={"reason": "x"},
        ).status_code
        == 403
    )
    assert (
        support.client.post(
            "/api/v1/platform/organisations/00000000-0000-0000-0000-000000000000/suspend",
            json={"reason": "x"},
        ).status_code
        == 403
    )
    assert (
        compliance.client.post(
            "/api/v1/platform/users/00000000-0000-0000-0000-000000000000/suspend",
            json={"reason": "x"},
        ).status_code
        == 403
    )
    assert (
        compliance.client.post(
            "/api/v1/platform/organisations/00000000-0000-0000-0000-000000000000/suspend",
            json={"reason": "x"},
        ).status_code
        == 403
    )
    assert compliance.client.get("/api/v1/platform/audit-events").status_code == 200

    async def _seed_org():
        async with migrated_session_factory() as session:
            async with session.begin():
                return await OrganisationService(session).create_organisation(
                    name="Org X", slug="org-x"
                )

    org = run_async(_seed_org())
    assert admin.client.get(f"/api/v1/organisations/{org.id}").status_code == 403
    assert (
        admin.client.get(f"/api/v1/platform/organisations/{org.id}").status_code == 200
    )

    assert (
        authenticated_client_factory(
            identity=identity_for("kc-tenant", "tenant@example.com"),
            database_url=migrated_database_url,
        )
        .client.get("/api/v1/platform/users")
        .status_code
        == 403
    )
