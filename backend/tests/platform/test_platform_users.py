from sqlalchemy import select

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.platform.models.platform_staff import PlatformStaffRole
from app.platform.services.platform_staff import PlatformStaffService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import build_identity


def _seed_staff(session_factory, user_id):
    async def _run():
        async with session_factory() as session:
            await PlatformStaffService(session).create_platform_staff(
                user_id=user_id, role=PlatformStaffRole.PLATFORM_ADMIN.value
            )
            await session.commit()

    run_async(_run())


def test_platform_admin_can_suspend_user_with_audit(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
):
    admin = authenticated_client_factory(
        identity=build_identity(external_auth_id="kc-admin", email="admin@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    user = authenticated_client_factory(
        identity=build_identity(external_auth_id="kc-user2", email="user2@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with admin.client as c:
        admin_me = c.get("/api/v1/users/me").json()
    with user.client as c:
        user_me = c.get("/api/v1/users/me").json()
    _seed_staff(migrated_session_factory, admin_me["id"])
    with admin.client as c:
        r = c.post(
            f"/api/v1/platform/users/{user_me['id']}/suspend",
            json={"reason": "abuse case"},
        )
    assert r.status_code == 200

    async def _events():
        async with migrated_session_factory() as s:
            rows = (
                (
                    await s.execute(
                        select(AuditEvent).where(
                            AuditEvent.action == AuditAction.USER_SUSPENDED.value
                        )
                    )
                )
                .scalars()
                .all()
            )
            return rows

    assert len(run_async(_events())) >= 1
