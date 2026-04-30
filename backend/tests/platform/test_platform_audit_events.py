from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def _seed_platform_staff(
    session_factory, *, external_auth_id: str, email: str, role: PlatformRole
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
            return user

    return run_async(_run())


def test_platform_admin_and_compliance_can_list_audit_events(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-pa",
        email="pa@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-co",
        email="co@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )

    for external_auth_id, email in (
        ("kc-pa", "pa@example.com"),
        ("kc-co", "co@example.com"),
    ):
        bundle = authenticated_client_factory(
            identity=identity_for(external_auth_id, email),
            database_url=migrated_database_url,
        )
        response = bundle.client.get("/api/v1/platform/audit-events")
        assert response.status_code == 200
        payload = response.json()
        assert "data" in payload
        assert "meta" in payload
        assert "links" in payload
        assert "total" in payload["meta"]
        assert "limit" in payload["meta"]
        assert "offset" in payload["meta"]


def test_support_agent_and_regular_user_cannot_list_full_audit_events(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-sa",
        email="sa@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    bundle = authenticated_client_factory(
        identity=identity_for("kc-sa", "sa@example.com"),
        database_url=migrated_database_url,
    )
    assert bundle.client.get("/api/v1/platform/audit-events").status_code == 403

    regular = authenticated_client_factory(
        identity=identity_for("kc-regular", "regular@example.com"),
        database_url=migrated_database_url,
    )
    assert regular.client.get("/api/v1/platform/audit-events").status_code == 403


def test_audit_events_pagination_validation(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-pa-2",
        email="pa2@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    bundle = authenticated_client_factory(
        identity=identity_for("kc-pa-2", "pa2@example.com"),
        database_url=migrated_database_url,
    )
    assert (
        bundle.client.get("/api/v1/platform/audit-events?limit=101").status_code == 422
    )
    assert (
        bundle.client.get("/api/v1/platform/audit-events?offset=-1").status_code == 422
    )
