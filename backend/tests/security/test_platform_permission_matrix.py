from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.audit.models.audit_event import AuditEvent
from app.organisations.repositories.organisations import OrganisationRepository
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


@dataclass(frozen=True)
class PlatformTargets:
    user_id: UUID
    organisation_id: UUID
    staff_id: UUID
    new_staff_user_id: UUID


READ_ENDPOINTS = [
    ("GET", "/api/v1/platform/me", None),
    ("GET", "/api/v1/platform/users", None),
    ("GET", "/api/v1/platform/users/limited", None),
    ("GET", "/api/v1/platform/users/{user_id}", None),
    ("GET", "/api/v1/platform/organisations", None),
    ("GET", "/api/v1/platform/organisations/limited", None),
    ("GET", "/api/v1/platform/organisations/{organisation_id}", None),
    ("GET", "/api/v1/platform/audit-events", None),
    ("GET", "/api/v1/platform/audit-events/limited", None),
    ("GET", "/api/v1/platform/staff", None),
    ("GET", "/api/v1/platform/staff/{staff_id}", None),
]

WRITE_ENDPOINTS = [
    ("POST", "/api/v1/platform/users/{user_id}/suspend", {"reason": "Matrix check"}),
    ("POST", "/api/v1/platform/users/{user_id}/restore", {"reason": "Matrix check"}),
    (
        "POST",
        "/api/v1/platform/organisations/{organisation_id}/suspend",
        {"reason": "Matrix check"},
    ),
    (
        "POST",
        "/api/v1/platform/organisations/{organisation_id}/restore",
        {"reason": "Matrix check"},
    ),
    (
        "PATCH",
        "/api/v1/platform/organisations/{organisation_id}",
        {"name": "Matrix Updated Organisation", "reason": "Matrix check"},
    ),
    (
        "POST",
        "/api/v1/platform/staff",
        {
            "user_id": "{new_staff_user_id}",
            "role": PlatformStaffRole.SUPPORT_AGENT.value,
            "reason": "Matrix check",
        },
    ),
    (
        "PATCH",
        "/api/v1/platform/staff/{staff_id}/role",
        {"role": PlatformStaffRole.COMPLIANCE_OFFICER.value, "reason": "Matrix check"},
    ),
    ("POST", "/api/v1/platform/staff/{staff_id}/suspend", {"reason": "Matrix check"}),
    ("POST", "/api/v1/platform/staff/{staff_id}/restore", {"reason": "Matrix check"}),
]

ALL_ENDPOINTS = [*READ_ENDPOINTS, *WRITE_ENDPOINTS]

SUPPORT_ALLOWED = {
    ("GET", "/api/v1/platform/me"),
    ("GET", "/api/v1/platform/users/limited"),
    ("GET", "/api/v1/platform/organisations/limited"),
    ("GET", "/api/v1/platform/audit-events/limited"),
}

COMPLIANCE_ALLOWED = {
    ("GET", "/api/v1/platform/me"),
    ("GET", "/api/v1/platform/users/limited"),
    ("GET", "/api/v1/platform/organisations/limited"),
    ("GET", "/api/v1/platform/audit-events"),
    ("GET", "/api/v1/platform/audit-events/limited"),
}


def _seed_user(
    session_factory, external_auth_id: str, email: str, *, status=UserStatus.ACTIVE
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                user.status = status
                user.first_name = "Matrix"
                user.last_name = "Actor"
                await session.flush()
            return user

    return run_async(_run())


def _seed_staff(
    session_factory,
    external_auth_id: str,
    email: str,
    role: PlatformStaffRole,
    *,
    user_status=UserStatus.ACTIVE,
    staff_status=PlatformStaffStatus.ACTIVE,
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


def _seed_targets(session_factory) -> PlatformTargets:
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                target_user = await UserService(session).provision_current_user(
                    identity_for("kc-matrix-target", "matrix-target@example.com")
                )
                new_staff_user = await UserService(session).provision_current_user(
                    identity_for("kc-matrix-new-staff", "matrix-new-staff@example.com")
                )
                org = await OrganisationRepository(session).create(
                    name="Matrix Organisation",
                    slug="matrix-organisation",
                )
                staff_user = await UserService(session).provision_current_user(
                    identity_for(
                        "kc-matrix-staff-target", "matrix-staff-target@example.com"
                    )
                )
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=staff_user.id,
                    role=PlatformStaffRole.SUPPORT_AGENT.value,
                )
            return PlatformTargets(
                user_id=target_user.id,
                organisation_id=org.id,
                staff_id=staff.id,
                new_staff_user_id=new_staff_user.id,
            )

    return run_async(_run())


def _format_path(path: str, targets: PlatformTargets) -> str:
    return path.format(
        user_id=targets.user_id,
        organisation_id=targets.organisation_id,
        staff_id=targets.staff_id,
    )


def _format_payload(payload: dict[str, object] | None, targets: PlatformTargets):
    if payload is None:
        return None
    return {
        key: str(value).format(new_staff_user_id=targets.new_staff_user_id)
        for key, value in payload.items()
    }


def _request(client, method: str, path: str, payload: dict[str, object] | None):
    if payload is not None:
        return client.request(method, path, json=payload)
    return client.request(method, path)


@pytest.mark.parametrize(("method", "path", "payload"), ALL_ENDPOINTS)
def test_platform_endpoints_reject_unauthenticated_requests(
    client, migrated_session_factory, method, path, payload
) -> None:
    targets = _seed_targets(migrated_session_factory)

    response = _request(
        client, method, _format_path(path, targets), _format_payload(payload, targets)
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "actor_kind",
    ["missing_local_user", "local_user", "suspended_local_user", "suspended_staff"],
)
@pytest.mark.parametrize(("method", "path", "payload"), ALL_ENDPOINTS)
def test_platform_endpoints_reject_non_platform_and_suspended_actors(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    actor_kind,
    method,
    path,
    payload,
) -> None:
    targets = _seed_targets(migrated_session_factory)
    if actor_kind == "missing_local_user":
        identity = identity_for("kc-matrix-missing", "matrix-missing@example.com")
    elif actor_kind == "local_user":
        user = _seed_user(
            migrated_session_factory, "kc-matrix-local", "matrix-local@example.com"
        )
        identity = identity_for(user.external_auth_id, user.email)
    elif actor_kind == "suspended_local_user":
        user = _seed_user(
            migrated_session_factory,
            "kc-matrix-suspended-user",
            "matrix-suspended-user@example.com",
            status=UserStatus.SUSPENDED,
        )
        identity = identity_for(user.external_auth_id, user.email)
    else:
        user = _seed_staff(
            migrated_session_factory,
            "kc-matrix-suspended-staff",
            "matrix-suspended-staff@example.com",
            PlatformStaffRole.PLATFORM_ADMIN,
            staff_status=PlatformStaffStatus.SUSPENDED,
        )[0]
        identity = identity_for(user.external_auth_id, user.email)
    bundle = authenticated_client_factory(
        identity=identity, database_url=migrated_database_url
    )

    response = _request(
        bundle.client,
        method,
        _format_path(path, targets),
        _format_payload(payload, targets),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform access denied"


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (PlatformStaffRole.SUPPORT_AGENT, SUPPORT_ALLOWED),
        (PlatformStaffRole.COMPLIANCE_OFFICER, COMPLIANCE_ALLOWED),
    ],
)
@pytest.mark.parametrize(("method", "path", "payload"), ALL_ENDPOINTS)
def test_platform_limited_roles_follow_permission_matrix(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    role,
    allowed,
    method,
    path,
    payload,
) -> None:
    targets = _seed_targets(migrated_session_factory)
    user = _seed_staff(
        migrated_session_factory,
        f"kc-matrix-{role.value}",
        f"matrix-{role.value}@example.com",
        role,
    )[0]
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = _request(
        bundle.client,
        method,
        _format_path(path, targets),
        _format_payload(payload, targets),
    )

    if (method, path) in allowed:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert response.json()["detail"] == "Platform access denied"


@pytest.mark.parametrize(("method", "path", "payload"), ALL_ENDPOINTS)
def test_platform_admin_can_access_platform_endpoints(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    method,
    path,
    payload,
) -> None:
    targets = _seed_targets(migrated_session_factory)
    user = _seed_staff(
        migrated_session_factory,
        "kc-matrix-admin",
        "matrix-admin@example.com",
        PlatformStaffRole.PLATFORM_ADMIN,
    )[0]
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = _request(
        bundle.client,
        method,
        _format_path(path, targets),
        _format_payload(payload, targets),
    )

    assert response.status_code in {200, 201}


def test_denied_platform_write_does_not_create_audit_event(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    targets = _seed_targets(migrated_session_factory)
    user = _seed_staff(
        migrated_session_factory,
        "kc-matrix-denied-write",
        "matrix-denied-write@example.com",
        PlatformStaffRole.SUPPORT_AGENT,
    )[0]
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    async def _audit_count() -> int:
        async with migrated_session_factory() as session:
            count = await session.execute(select(func.count()).select_from(AuditEvent))
            return int(count.scalar_one())

    before = run_async(_audit_count())
    response = bundle.client.post(
        f"/api/v1/platform/users/{targets.user_id}/suspend",
        json={"reason": "Denied write"},
    )
    after = run_async(_audit_count())

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform access denied"
    assert after == before
