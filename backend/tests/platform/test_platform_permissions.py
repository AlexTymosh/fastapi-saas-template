from app.platform.models.platform_staff import PlatformStaffRole
from app.platform.services.platform_staff import PlatformStaffService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import build_identity


def _seed_staff(session_factory, user_id, role=PlatformStaffRole.PLATFORM_ADMIN.value):
    async def _run():
        async with session_factory() as session:
            await PlatformStaffService(session).create_platform_staff(
                user_id=user_id, role=role
            )
            await session.commit()

    run_async(_run())


def test_jwt_platform_admin_without_platform_staff_gets_403(
    authenticated_client_factory, migrated_database_url: str
):
    bundle = authenticated_client_factory(
        identity=build_identity(
            external_auth_id="kc-no-staff",
            email="nostaff@example.com",
            roles=["platform_admin"],
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with bundle.client as client:
        response = client.get("/api/v1/platform/users")
    assert response.status_code == 403


def test_active_platform_staff_can_access_platform_users(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
):
    bundle = authenticated_client_factory(
        identity=build_identity(external_auth_id="kc-staff", email="staff@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with bundle.client as client:
        me = client.get("/api/v1/users/me").json()
    _seed_staff(migrated_session_factory, me["id"])
    with bundle.client as client:
        response = client.get("/api/v1/platform/users")
    assert response.status_code == 200
    assert "data" in response.json()
