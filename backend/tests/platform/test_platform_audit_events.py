from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def _seed_staff(
    session_factory, *, external_auth_id: str, email: str, role: PlatformRole
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id, role=role.value
                )

    run_async(_run())


def test_platform_audit_events_authorisation_and_envelope(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-pa-admin",
        email="pa-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-pa-compliance",
        email="pa-compliance@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )
    _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-pa-support",
        email="pa-support@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )

    admin = authenticated_client_factory(
        identity=identity_for("kc-pa-admin", "pa-admin@example.com"),
        database_url=migrated_database_url,
    )
    compliance = authenticated_client_factory(
        identity=identity_for("kc-pa-compliance", "pa-compliance@example.com"),
        database_url=migrated_database_url,
    )
    support = authenticated_client_factory(
        identity=identity_for("kc-pa-support", "pa-support@example.com"),
        database_url=migrated_database_url,
    )
    tenant = authenticated_client_factory(
        identity=identity_for("kc-tenant-only", "tenant-only@example.com"),
        database_url=migrated_database_url,
    )

    admin_resp = admin.client.get("/api/v1/platform/audit-events")
    assert admin_resp.status_code == 200
    payload = admin_resp.json()
    assert "data" in payload and "meta" in payload and "links" in payload
    assert {"total", "limit", "offset"}.issubset(payload["meta"].keys())

    assert compliance.client.get("/api/v1/platform/audit-events").status_code == 200
    assert support.client.get("/api/v1/platform/audit-events").status_code == 403
    assert tenant.client.get("/api/v1/platform/audit-events").status_code == 403
    assert (
        admin.client.get("/api/v1/platform/audit-events?limit=101").status_code == 422
    )
    assert (
        admin.client.get("/api/v1/platform/audit-events?offset=-1").status_code == 422
    )
