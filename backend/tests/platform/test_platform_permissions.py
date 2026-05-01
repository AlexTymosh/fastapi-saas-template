from types import SimpleNamespace

from sqlalchemy import select

from app.core.platform.dependencies import require_platform_permission
from app.core.platform.permissions import PlatformPermission, PlatformRole
from app.memberships.models.membership import Membership
from app.organisations.models.organisation import Organisation
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def _seed_platform_staff(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    role: str,
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
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role,
                )
                staff.status = staff_status.value
                await session.flush()
            return user

    return run_async(_run())


def test_permission_matrix_core(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    suspended_user = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-su",
        email="su@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
        user_status=UserStatus.SUSPENDED,
    )
    suspended_staff = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-ss",
        email="ss@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
        staff_status=PlatformStaffStatus.SUSPENDED,
    )
    support = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-support",
        email="support@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    compliance = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-comp",
        email="comp@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER.value,
    )
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-admin",
        email="admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _seed_org():
        async with migrated_session_factory() as session:
            async with session.begin():
                org = Organisation(name="Zulu", slug="zulu")
                session.add(org)
            return org

    org = run_async(_seed_org())

    for user in (suspended_user, suspended_staff):
        bundle = authenticated_client_factory(
            identity=identity_for(user.external_auth_id, user.email),
            database_url=migrated_database_url,
        )
        assert bundle.client.get("/api/v1/platform/users").status_code == 403

    support_bundle = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
    )
    assert (
        support_bundle.client.post(
            f"/api/v1/platform/users/{admin.id}/suspend", json={"reason": "r"}
        ).status_code
        == 403
    )
    assert (
        support_bundle.client.post(
            f"/api/v1/platform/organisations/{org.id}/suspend", json={"reason": "r"}
        ).status_code
        == 403
    )

    comp_bundle = authenticated_client_factory(
        identity=identity_for(compliance.external_auth_id, compliance.email),
        database_url=migrated_database_url,
    )
    assert (
        comp_bundle.client.post(
            f"/api/v1/platform/users/{admin.id}/suspend", json={"reason": "r"}
        ).status_code
        == 403
    )
    assert (
        comp_bundle.client.post(
            f"/api/v1/platform/organisations/{org.id}/suspend", json={"reason": "r"}
        ).status_code
        == 403
    )
    assert comp_bundle.client.get("/api/v1/platform/audit-events").status_code == 200

    admin_bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    assert admin_bundle.client.get(f"/api/v1/organisations/{org.id}").status_code == 403
    assert (
        admin_bundle.client.get(f"/api/v1/platform/organisations/{org.id}").status_code
        == 200
    )

    regular_bundle = authenticated_client_factory(
        identity=identity_for("kc-regular-p", "regular-p@example.com"),
        database_url=migrated_database_url,
    )
    assert regular_bundle.client.get("/api/v1/platform/users").status_code == 403


def test_invalid_platform_staff_role_is_denied_without_value_error(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
):
    user = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-invalid-role",
        email="invalid-role@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _fake_get_by_user_id(self, user_id):
        return SimpleNamespace(
            user_id=user_id,
            role="invalid_role",
            status=PlatformStaffStatus.ACTIVE.value,
        )

    monkeypatch.setattr(
        PlatformStaffRepository,
        "get_by_user_id",
        _fake_get_by_user_id,
    )

    dependency = require_platform_permission(PlatformPermission.USERS_READ)

    async def _assert_denied():
        async with migrated_session_factory() as session:
            try:
                await dependency(
                    identity=identity_for(user.external_auth_id, user.email),
                    db_session=session,
                )
            except Exception as exc:  # noqa: BLE001
                assert exc.__class__.__name__ == "ForbiddenError"
                return
            raise AssertionError("Expected forbidden access for invalid role")

    run_async(_assert_denied())

    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )
    assert bundle.client.get("/api/v1/platform/users").status_code == 403


def test_platform_endpoint_does_not_provision_missing_user(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    bundle = authenticated_client_factory(
        identity=identity_for("kc-missing-local", "missing-local@example.com"),
        database_url=migrated_database_url,
    )
    assert bundle.client.get("/api/v1/platform/users").status_code == 403

    async def _assert_missing_user():
        async with migrated_session_factory() as session:
            user = await UserService(session).user_repository.get_by_external_auth_id(
                "kc-missing-local"
            )
            assert user is None

    run_async(_assert_missing_user())


def test_platform_staff_access_does_not_require_tenant_membership(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    staff_user = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-no-membership",
        email="platform-no-membership@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _assert_no_membership():
        async with migrated_session_factory() as session:
            memberships = await session.execute(
                select(Membership).where(Membership.user_id == staff_user.id)
            )
            assert list(memberships.scalars().all()) == []

    run_async(_assert_no_membership())

    bundle = authenticated_client_factory(
        identity=identity_for(staff_user.external_auth_id, staff_user.email),
        database_url=migrated_database_url,
    )
    assert bundle.client.get("/api/v1/platform/users").status_code == 200


def test_compliance_officer_permissions_exclude_gdpr_erase():
    from app.core.platform.permissions import ROLE_PERMISSIONS

    perms = ROLE_PERMISSIONS[PlatformRole.COMPLIANCE_OFFICER]
    assert PlatformPermission.GDPR_ERASE not in perms
    assert PlatformPermission.GDPR_EXPORT in perms


def test_platform_admin_permissions_include_gdpr_erase():
    from app.core.platform.permissions import ROLE_PERMISSIONS

    perms = ROLE_PERMISSIONS[PlatformRole.PLATFORM_ADMIN]
    assert PlatformPermission.GDPR_ERASE in perms
