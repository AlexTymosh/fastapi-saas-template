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
                await session.flush()
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


def test_platform_staff_management_flow(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    regular = _seed_user(migrated_session_factory, ext_id="u1", email="u1@example.com")
    support_user, support_staff = _seed_staff(
        migrated_session_factory,
        ext_id="sup",
        email="sup@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    comp_user, _ = _seed_staff(
        migrated_session_factory,
        ext_id="comp",
        email="comp@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER.value,
    )
    admin_user, admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="adm",
        email="adm@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    regular_client = authenticated_client_factory(
        identity=identity_for(regular.external_auth_id, regular.email),
        database_url=migrated_database_url,
    ).client
    assert regular_client.get("/api/v1/platform/staff").status_code == 403

    support_client = authenticated_client_factory(
        identity=identity_for(support_user.external_auth_id, support_user.email),
        database_url=migrated_database_url,
    ).client
    assert (
        support_client.post(
            "/api/v1/platform/staff",
            json={"user_id": str(regular.id), "role": "support_agent", "reason": "r"},
        ).status_code
        == 403
    )

    comp_client = authenticated_client_factory(
        identity=identity_for(comp_user.external_auth_id, comp_user.email),
        database_url=migrated_database_url,
    ).client
    assert (
        comp_client.post(
            "/api/v1/platform/staff",
            json={"user_id": str(regular.id), "role": "support_agent", "reason": "r"},
        ).status_code
        == 403
    )

    admin_client = authenticated_client_factory(
        identity=identity_for(admin_user.external_auth_id, admin_user.email),
        database_url=migrated_database_url,
    ).client
    list_response = admin_client.get("/api/v1/platform/staff")
    assert list_response.status_code == 200
    assert set(list_response.json().keys()) == {"data", "meta", "links"}

    target = _seed_user(migrated_session_factory, ext_id="new", email="new@example.com")
    create_response = admin_client.post(
        "/api/v1/platform/staff",
        json={
            "user_id": str(target.id),
            "role": "support_agent",
            "reason": "on-call support",
        },
    )
    assert create_response.status_code == 200

    missing_response = admin_client.post(
        "/api/v1/platform/staff",
        json={
            "user_id": "82afebc8-53a8-4b58-a525-30f636616f14",
            "role": "support_agent",
            "reason": "r",
        },
    )
    assert missing_response.status_code == 404

    duplicate_response = admin_client.post(
        "/api/v1/platform/staff",
        json={"user_id": str(target.id), "role": "support_agent", "reason": "r"},
    )
    assert duplicate_response.status_code == 409

    role_response = admin_client.patch(
        f"/api/v1/platform/staff/{support_staff.id}/role",
        json={"role": "compliance_officer", "reason": "rotation"},
    )
    assert role_response.status_code == 200

    own_demote = admin_client.patch(
        f"/api/v1/platform/staff/{admin_staff.id}/role",
        json={"role": "support_agent", "reason": "self"},
    )
    assert own_demote.status_code == 409

    last_admin_demote = admin_client.patch(
        f"/api/v1/platform/staff/{admin_staff.id}/role",
        json={"role": "compliance_officer", "reason": "self"},
    )
    assert last_admin_demote.status_code == 409

    suspend_response = admin_client.post(
        f"/api/v1/platform/staff/{support_staff.id}/suspend",
        json={"reason": "policy breach"},
    )
    assert suspend_response.status_code == 200

    self_suspend = admin_client.post(
        f"/api/v1/platform/staff/{admin_staff.id}/suspend", json={"reason": "no"}
    )
    assert self_suspend.status_code == 409

    last_admin_suspend = admin_client.post(
        f"/api/v1/platform/staff/{admin_staff.id}/suspend", json={"reason": "no"}
    )
    assert last_admin_suspend.status_code == 409

    restore_response = admin_client.post(
        f"/api/v1/platform/staff/{support_staff.id}/restore",
        json={"reason": "appeal accepted"},
    )
    assert restore_response.status_code == 200

    already_active_restore = admin_client.post(
        f"/api/v1/platform/staff/{support_staff.id}/restore", json={"reason": "dup"}
    )
    assert already_active_restore.status_code == 409

    blank_reason_response = admin_client.post(
        "/api/v1/platform/staff",
        json={
            "user_id": str(
                _seed_user(
                    migrated_session_factory, ext_id="blank", email="blank@example.com"
                ).id
            ),
            "role": "support_agent",
            "reason": "   ",
        },
    )
    assert blank_reason_response.status_code == 422

    async def _verify_audit():
        async with migrated_session_factory() as session:
            rows = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action.in_(
                            [
                                AuditAction.PLATFORM_STAFF_CREATED.value,
                                AuditAction.PLATFORM_STAFF_ROLE_CHANGED.value,
                                AuditAction.PLATFORM_STAFF_SUSPENDED.value,
                                AuditAction.PLATFORM_STAFF_RESTORED.value,
                            ]
                        )
                    )
                )
            ).all()
            assert len(rows) >= 4

    run_async(_verify_audit())
