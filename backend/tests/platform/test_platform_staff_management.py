from types import SimpleNamespace

import pytest

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.core.platform import PlatformRole
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def _seed_user(
    session_factory, *, ext_id: str, email: str, status: UserStatus = UserStatus.ACTIVE
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(ext_id, email)
                )
                user.status = status
            return user

    return run_async(_run())


def _seed_staff(
    session_factory,
    *,
    ext_id: str,
    email: str,
    role: str,
    status: PlatformStaffStatus = PlatformStaffStatus.ACTIVE,
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(ext_id, email)
                )
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id, role=role
                )
                staff.status = status.value
                await session.flush()
            return user, staff

    return run_async(_run())


@pytest.fixture
def staff_env(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    # Seed all the necessary users and staff accounts for tests
    regular = _seed_user(
        migrated_session_factory, ext_id="kc-reg", email="reg@example.com"
    )
    support_user, support_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-sup",
        email="sup@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    comp_user, _ = _seed_staff(
        migrated_session_factory,
        ext_id="kc-comp-s",
        email="comp-s@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER.value,
    )
    admin_user, admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-admin-s",
        email="admin-s@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    # Generate authenticated clients
    regular_bundle = authenticated_client_factory(
        identity=identity_for(regular.external_auth_id, regular.email),
        database_url=migrated_database_url,
    )
    support_bundle = authenticated_client_factory(
        identity=identity_for(support_user.external_auth_id, support_user.email),
        database_url=migrated_database_url,
    )
    comp_bundle = authenticated_client_factory(
        identity=identity_for(comp_user.external_auth_id, comp_user.email),
        database_url=migrated_database_url,
    )
    admin_bundle = authenticated_client_factory(
        identity=identity_for(admin_user.external_auth_id, admin_user.email),
        database_url=migrated_database_url,
    )

    # Return as a namespace for easy dot-notation access in tests
    return SimpleNamespace(
        regular=regular,
        support_user=support_user,
        support_staff=support_staff,
        comp_user=comp_user,
        admin_user=admin_user,
        admin_staff=admin_staff,
        regular_bundle=regular_bundle,
        support_bundle=support_bundle,
        comp_bundle=comp_bundle,
        admin_bundle=admin_bundle,
    )


def test_platform_staff_access_control(staff_env):
    # Ensure regular users, support, and compliance cannot access/modify staff
    assert (
        staff_env.regular_bundle.client.get("/api/v1/platform/staff").status_code == 403
    )

    assert (
        staff_env.support_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": str(staff_env.regular.id),
                "role": "support_agent",
                "reason": "r",
            },
        ).status_code
        == 403
    )

    assert (
        staff_env.comp_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": str(staff_env.regular.id),
                "role": "support_agent",
                "reason": "r",
            },
        ).status_code
        == 403
    )

    # Ensure admin has access and receives the correct paginated schema
    list_response = staff_env.admin_bundle.client.get("/api/v1/platform/staff")
    assert list_response.status_code == 200
    assert set(list_response.json().keys()) == {"data", "meta", "links"}


def test_platform_staff_creation(staff_env, migrated_session_factory):
    # Verify successful creation
    candidate = _seed_user(
        migrated_session_factory, ext_id="kc-candidate", email="candidate@example.com"
    )
    create_response = staff_env.admin_bundle.client.post(
        "/api/v1/platform/staff",
        json={
            "user_id": str(candidate.id),
            "role": "support_agent",
            "reason": "new support",
        },
    )
    assert create_response.status_code == 200

    # Verify duplicate prevention (candidate again)
    assert (
        staff_env.admin_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": str(candidate.id),
                "role": "support_agent",
                "reason": "dup",
            },
        ).status_code
        == 409
    )

    # Verify duplicate prevention (existing admin)
    assert (
        staff_env.admin_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": str(staff_env.admin_staff.user_id),
                "role": "support_agent",
                "reason": "dup2",
            },
        ).status_code
        == 409
    )

    # Verify 404 on missing user id
    assert (
        staff_env.admin_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "role": "support_agent",
                "reason": "missing",
            },
        ).status_code
        == 404
    )


def test_platform_staff_lifecycle_management(staff_env):
    # Verify valid role change
    role_change = staff_env.admin_bundle.client.patch(
        f"/api/v1/platform/staff/{staff_env.support_staff.id}/role",
        json={"role": "compliance_officer", "reason": "rotate"},
    )
    assert role_change.status_code == 200

    # Verify admins cannot modify their own roles or suspend themselves
    assert (
        staff_env.admin_bundle.client.patch(
            f"/api/v1/platform/staff/{staff_env.admin_staff.id}/role",
            json={"role": "support_agent", "reason": "self"},
        ).status_code
        == 409
    )
    assert (
        staff_env.admin_bundle.client.post(
            f"/api/v1/platform/staff/{staff_env.admin_staff.id}/suspend",
            json={"reason": "self"},
        ).status_code
        == 409
    )
    assert (
        staff_env.admin_bundle.client.patch(
            f"/api/v1/platform/staff/{staff_env.admin_staff.id}/role",
            json={"role": "compliance_officer", "reason": "last"},
        ).status_code
        == 409
    )

    # Verify suspension flow
    assert (
        staff_env.admin_bundle.client.post(
            f"/api/v1/platform/staff/{staff_env.support_staff.id}/suspend",
            json={"reason": "policy"},
        ).status_code
        == 201
    )

    # Verify restore flow
    assert (
        staff_env.admin_bundle.client.post(
            f"/api/v1/platform/staff/{staff_env.support_staff.id}/restore",
            json={"reason": "policy done"},
        ).status_code
        == 200
    )

    # Verify prevention of redundant restores
    assert (
        staff_env.admin_bundle.client.post(
            f"/api/v1/platform/staff/{staff_env.support_staff.id}/restore",
            json={"reason": "again"},
        ).status_code
        == 409
    )


def test_platform_staff_validation(staff_env):
    # Check that providing an empty reason triggers 422 Unprocessable Entity
    for url in [
        "/api/v1/platform/staff",
        f"/api/v1/platform/staff/{staff_env.support_staff.id}/role",
        f"/api/v1/platform/staff/{staff_env.support_staff.id}/suspend",
        f"/api/v1/platform/staff/{staff_env.support_staff.id}/restore",
    ]:
        method = staff_env.admin_bundle.client.post
        payload = {"reason": "   "}
        if url.endswith("/role"):
            method = staff_env.admin_bundle.client.patch
            payload["role"] = "support_agent"
        elif url.endswith("/staff"):
            payload = {
                "user_id": str(staff_env.regular.id),
                "role": "support_agent",
                "reason": "   ",
            }
        assert method(url, json=payload).status_code == 422


def test_platform_staff_audit_events(staff_env, migrated_session_factory):
    # Perform actions within this isolated test context to generate the audit records
    candidate = _seed_user(
        migrated_session_factory, ext_id="kc-candidate-audit", email="audit@example.com"
    )

    staff_env.admin_bundle.client.post(
        "/api/v1/platform/staff",
        json={"user_id": str(candidate.id), "role": "support_agent", "reason": "new"},
    )
    staff_env.admin_bundle.client.patch(
        f"/api/v1/platform/staff/{staff_env.support_staff.id}/role",
        json={"role": "compliance_officer", "reason": "rotate"},
    )
    staff_env.admin_bundle.client.post(
        f"/api/v1/platform/staff/{staff_env.support_staff.id}/suspend",
        json={"reason": "policy"},
    )
    staff_env.admin_bundle.client.post(
        f"/api/v1/platform/staff/{staff_env.support_staff.id}/restore",
        json={"reason": "done"},
    )

    # Verify that all expected audit actions were inserted into the database
    async def _audit_verify():
        async with migrated_session_factory() as session:
            actions = {
                AuditAction.PLATFORM_STAFF_CREATED.value,
                AuditAction.PLATFORM_STAFF_ROLE_CHANGED.value,
                AuditAction.PLATFORM_STAFF_SUSPENDED.value,
                AuditAction.PLATFORM_STAFF_RESTORED.value,
            }
            rows = (
                await session.execute(
                    AuditEvent.__table__.select().where(AuditEvent.action.in_(actions))
                )
            ).all()
            assert len(rows) >= 4

    run_async(_audit_verify())
