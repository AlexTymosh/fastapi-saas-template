from app.audit.models.audit_event import AuditAction, AuditEvent
from app.core.platform.permissions import PlatformRole
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


def test_platform_staff_management_endpoints(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
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

    regular_bundle = authenticated_client_factory(
        identity=identity_for(regular.external_auth_id, regular.email),
        database_url=migrated_database_url,
    )
    assert regular_bundle.client.get("/api/v1/platform/staff").status_code == 403

    support_bundle = authenticated_client_factory(
        identity=identity_for(support_user.external_auth_id, support_user.email),
        database_url=migrated_database_url,
    )
    assert (
        support_bundle.client.post(
            "/api/v1/platform/staff",
            json={"user_id": str(regular.id), "role": "support_agent", "reason": "r"},
        ).status_code
        == 403
    )

    comp_bundle = authenticated_client_factory(
        identity=identity_for(comp_user.external_auth_id, comp_user.email),
        database_url=migrated_database_url,
    )
    assert (
        comp_bundle.client.post(
            "/api/v1/platform/staff",
            json={"user_id": str(regular.id), "role": "support_agent", "reason": "r"},
        ).status_code
        == 403
    )

    admin_bundle = authenticated_client_factory(
        identity=identity_for(admin_user.external_auth_id, admin_user.email),
        database_url=migrated_database_url,
    )
    list_response = admin_bundle.client.get("/api/v1/platform/staff")
    assert list_response.status_code == 200
    assert set(list_response.json().keys()) == {"data", "meta", "links"}

    candidate = _seed_user(
        migrated_session_factory, ext_id="kc-candidate", email="candidate@example.com"
    )
    create_response = admin_bundle.client.post(
        "/api/v1/platform/staff",
        json={
            "user_id": str(candidate.id),
            "role": "support_agent",
            "reason": "new support",
        },
    )
    assert create_response.status_code == 200
    assert (
        admin_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": str(candidate.id),
                "role": "support_agent",
                "reason": "dup",
            },
        ).status_code
        == 409
    )
    assert (
        admin_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": str(admin_staff.user_id),
                "role": "support_agent",
                "reason": "dup2",
            },
        ).status_code
        == 409
    )
    assert (
        admin_bundle.client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "role": "support_agent",
                "reason": "missing",
            },
        ).status_code
        == 404
    )

    role_change = admin_bundle.client.patch(
        f"/api/v1/platform/staff/{support_staff.id}/role",
        json={"role": "compliance_officer", "reason": "rotate"},
    )
    assert role_change.status_code == 200
    assert (
        admin_bundle.client.patch(
            f"/api/v1/platform/staff/{admin_staff.id}/role",
            json={"role": "support_agent", "reason": "self"},
        ).status_code
        == 409
    )
    assert (
        admin_bundle.client.post(
            f"/api/v1/platform/staff/{admin_staff.id}/suspend", json={"reason": "self"}
        ).status_code
        == 409
    )
    assert (
        admin_bundle.client.patch(
            f"/api/v1/platform/staff/{admin_staff.id}/role",
            json={"role": "compliance_officer", "reason": "last"},
        ).status_code
        == 409
    )
    assert (
        admin_bundle.client.post(
            f"/api/v1/platform/staff/{support_staff.id}/suspend",
            json={"reason": "policy"},
        ).status_code
        == 200
    )
    assert (
        admin_bundle.client.post(
            f"/api/v1/platform/staff/{support_staff.id}/restore",
            json={"reason": "policy done"},
        ).status_code
        == 200
    )
    assert (
        admin_bundle.client.post(
            f"/api/v1/platform/staff/{support_staff.id}/restore",
            json={"reason": "again"},
        ).status_code
        == 409
    )

    for url in [
        "/api/v1/platform/staff",
        f"/api/v1/platform/staff/{support_staff.id}/role",
        f"/api/v1/platform/staff/{support_staff.id}/suspend",
        f"/api/v1/platform/staff/{support_staff.id}/restore",
    ]:
        method = admin_bundle.client.post
        payload = {"reason": "   "}
        if url.endswith("/role"):
            method = admin_bundle.client.patch
            payload["role"] = "support_agent"
        elif url.endswith("/staff"):
            payload = {
                "user_id": str(regular.id),
                "role": "support_agent",
                "reason": "   ",
            }
        assert method(url, json=payload).status_code == 422

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
