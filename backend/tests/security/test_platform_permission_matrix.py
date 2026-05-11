from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import pytest

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.repositories.audit_events import AuditEventRepository
from app.core.platform.permissions import PlatformRole
from app.organisations.repositories.organisations import OrganisationRepository
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


@dataclass(frozen=True)
class MatrixTargets:
    user_id: UUID
    organisation_id: UUID
    staff_id: UUID
    staff_user_id: UUID
    staff_create_user_id: UUID


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
                await session.flush()
            return user

    return run_async(_run())


def _seed_staff_actor(
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
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
                staff.status = staff_status.value
                await session.flush()
            return user, staff

    return run_async(_run())


@pytest.fixture
def matrix_targets(migrated_session_factory) -> MatrixTargets:
    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                target_user = await UserService(session).provision_current_user(
                    identity_for("kc-matrix-target-user", "matrix-target@example.com")
                )
                staff_user = await UserService(session).provision_current_user(
                    identity_for(
                        "kc-matrix-target-staff", "matrix-target-staff@example.com"
                    )
                )
                staff_create_user = await UserService(session).provision_current_user(
                    identity_for(
                        "kc-matrix-create-staff-user", "matrix-create-staff@example.com"
                    )
                )
                org = await OrganisationRepository(session).create(
                    name="Matrix Organisation",
                    slug="matrix-org",
                )
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=staff_user.id,
                    role=PlatformRole.SUPPORT_AGENT.value,
                )
                await AuditEventRepository(session).create(
                    actor_user_id=target_user.id,
                    category=AuditCategory.PLATFORM,
                    action=AuditAction.USER_RESTORED,
                    target_type=AuditTargetType.USER,
                    target_id=target_user.id,
                )
                await session.flush()
            return MatrixTargets(
                user_id=target_user.id,
                organisation_id=org.id,
                staff_id=staff.id,
                staff_user_id=staff_user.id,
                staff_create_user_id=staff_create_user.id,
            )

    return run_async(_run())


def _platform_endpoints(targets: MatrixTargets):
    reason = {"reason": "Permission matrix check"}
    return [
        (
            "GET",
            "/api/v1/platform/me",
            None,
            {"support_agent", "compliance_officer", "platform_admin"},
        ),
        ("GET", "/api/v1/platform/users", None, {"platform_admin"}),
        (
            "GET",
            "/api/v1/platform/users/limited",
            None,
            {"support_agent", "compliance_officer", "platform_admin"},
        ),
        ("GET", f"/api/v1/platform/users/{targets.user_id}", None, {"platform_admin"}),
        (
            "POST",
            f"/api/v1/platform/users/{targets.user_id}/suspend",
            reason,
            {"platform_admin"},
        ),
        (
            "POST",
            f"/api/v1/platform/users/{targets.user_id}/restore",
            reason,
            {"platform_admin"},
        ),
        ("GET", "/api/v1/platform/organisations", None, {"platform_admin"}),
        (
            "GET",
            "/api/v1/platform/organisations/limited",
            None,
            {"support_agent", "compliance_officer", "platform_admin"},
        ),
        (
            "GET",
            f"/api/v1/platform/organisations/{targets.organisation_id}",
            None,
            {"platform_admin"},
        ),
        (
            "POST",
            f"/api/v1/platform/organisations/{targets.organisation_id}/suspend",
            reason,
            {"platform_admin"},
        ),
        (
            "POST",
            f"/api/v1/platform/organisations/{targets.organisation_id}/restore",
            reason,
            {"platform_admin"},
        ),
        (
            "PATCH",
            f"/api/v1/platform/organisations/{targets.organisation_id}",
            {
                "name": "Matrix Organisation Updated",
                "reason": "Permission matrix check",
            },
            {"platform_admin"},
        ),
        (
            "GET",
            "/api/v1/platform/audit-events",
            None,
            {"compliance_officer", "platform_admin"},
        ),
        (
            "GET",
            "/api/v1/platform/audit-events/limited",
            None,
            {"support_agent", "compliance_officer", "platform_admin"},
        ),
        ("GET", "/api/v1/platform/staff", None, {"platform_admin"}),
        ("GET", f"/api/v1/platform/staff/{targets.staff_id}", None, {"platform_admin"}),
        (
            "POST",
            "/api/v1/platform/staff",
            {
                "user_id": str(targets.staff_create_user_id),
                "role": "support_agent",
                "reason": "Permission matrix check",
            },
            {"platform_admin"},
        ),
        (
            "PATCH",
            f"/api/v1/platform/staff/{targets.staff_id}/role",
            {"role": "compliance_officer", "reason": "Permission matrix check"},
            {"platform_admin"},
        ),
        (
            "POST",
            f"/api/v1/platform/staff/{targets.staff_id}/suspend",
            reason,
            {"platform_admin"},
        ),
        (
            "POST",
            f"/api/v1/platform/staff/{targets.staff_id}/restore",
            reason,
            {"platform_admin"},
        ),
    ]


def _request(client, method: str, path: str, payload: dict[str, object] | None):
    return (
        client.request(method, path, json=payload)
        if payload is not None
        else client.request(method, path)
    )


@pytest.mark.parametrize(
    "method,path,payload,allowed_roles",
    _platform_endpoints(
        MatrixTargets(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), UUID(int=5))
    ),
)
def test_platform_routes_require_authentication(
    client_factory,
    migrated_database_url,
    method: str,
    path: str,
    payload,
    allowed_roles,
) -> None:
    _ = allowed_roles
    with client_factory(database_url=migrated_database_url) as client:
        response = _request(client, method, path, payload)

    assert response.status_code == 401


@pytest.mark.parametrize(
    "actor_factory",
    [
        lambda session_factory: identity_for(
            "kc-matrix-missing", "matrix-missing@example.com"
        ),
        lambda session_factory: identity_for(
            _seed_local_user(
                session_factory,
                external_auth_id="kc-matrix-local-no-staff",
                email="matrix-local-no-staff@example.com",
            ).external_auth_id,
            "matrix-local-no-staff@example.com",
        ),
        lambda session_factory: identity_for(
            _seed_local_user(
                session_factory,
                external_auth_id="kc-matrix-suspended-local",
                email="matrix-suspended-local@example.com",
                user_status=UserStatus.SUSPENDED,
            ).external_auth_id,
            "matrix-suspended-local@example.com",
        ),
        lambda session_factory: identity_for(
            _seed_staff_actor(
                session_factory,
                external_auth_id="kc-matrix-suspended-staff",
                email="matrix-suspended-staff@example.com",
                role=PlatformRole.PLATFORM_ADMIN,
                staff_status=PlatformStaffStatus.SUSPENDED,
            )[0].external_auth_id,
            "matrix-suspended-staff@example.com",
        ),
    ],
)
def test_non_platform_and_suspended_actors_receive_generic_platform_denial(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    matrix_targets: MatrixTargets,
    actor_factory: Callable,
) -> None:
    identity = actor_factory(migrated_session_factory)
    bundle = authenticated_client_factory(
        identity=identity,
        database_url=migrated_database_url,
    )

    for method, path, payload, _allowed_roles in _platform_endpoints(matrix_targets):
        response = _request(bundle.client, method, path, payload)
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["detail"] == "Platform access denied"


@pytest.mark.parametrize(
    "role",
    [
        PlatformRole.SUPPORT_AGENT,
        PlatformRole.COMPLIANCE_OFFICER,
        PlatformRole.PLATFORM_ADMIN,
    ],
)
def test_platform_role_permission_matrix(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    matrix_targets: MatrixTargets,
    role: PlatformRole,
) -> None:
    actor = _seed_staff_actor(
        migrated_session_factory,
        external_auth_id=f"kc-matrix-{role.value}",
        email=f"matrix-{role.value}@example.com",
        role=role,
    )[0]
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    for method, path, payload, allowed_roles in _platform_endpoints(matrix_targets):
        response = _request(bundle.client, method, path, payload)
        if role.value in allowed_roles:
            assert response.status_code < 400, (role.value, method, path, response.text)
        else:
            assert response.status_code == 403, (
                role.value,
                method,
                path,
                response.text,
            )
            assert response.json()["detail"] == "Platform access denied"


def test_denied_platform_write_does_not_create_audit_event(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    matrix_targets: MatrixTargets,
) -> None:
    actor = _seed_staff_actor(
        migrated_session_factory,
        external_auth_id="kc-matrix-denied-write",
        email="matrix-denied-write@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )[0]
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.post(
        f"/api/v1/platform/users/{matrix_targets.user_id}/suspend",
        json={"reason": "Should not audit"},
    )

    assert response.status_code == 403

    async def _count_matching_events() -> int:
        async with migrated_session_factory() as session:
            rows, total = await AuditEventRepository(session).list_events(
                limit=100,
                offset=0,
                category=AuditCategory.PLATFORM,
                action=AuditAction.USER_SUSPENDED,
                target_type=AuditTargetType.USER,
                target_id=matrix_targets.user_id,
            )
            assert rows == []
            return total

    assert run_async(_count_matching_events()) == 0
