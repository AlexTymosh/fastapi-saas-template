import pytest

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditEvent
from app.audit.services.audit_events import AuditEventService
from app.core.platform.actors import PlatformActor
from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.platform.services.platform_users import PlatformUsersService
from app.users.models.user import User, UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def _seed_platform_admin(session_factory, *, external_auth_id: str, email: str):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=PlatformRole.PLATFORM_ADMIN.value,
                )
            return user

    return run_async(_run())


def test_suspend_user_commits_and_writes_audit(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-admin",
        email="platform-admin@example.com",
    )
    target = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-target-user",
        email="target-user@example.com",
    )

    bundle = authenticated_client_factory(
        identity=identity_for("kc-platform-admin", "platform-admin@example.com"),
        database_url=migrated_database_url,
    )
    response = bundle.client.post(
        f"/api/v1/platform/users/{target.id}/suspend",
        json={"reason": "incident investigation"},
    )
    assert response.status_code == 200

    async def _verify():
        async with migrated_session_factory() as session:
            updated = await session.get(User, target.id)
            assert updated is not None
            assert updated.status == UserStatus.SUSPENDED
            event = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.USER_SUSPENDED.value,
                        AuditEvent.target_id == target.id,
                    )
                )
            ).first()
            assert event is not None

    run_async(_verify())


def test_suspend_user_rolls_back_on_audit_failure(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-admin-fail",
        email="platform-admin-fail@example.com",
    )
    target = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-target-fail",
        email="target-fail@example.com",
    )

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditEventService, "record_event", _raise)

    bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-platform-admin-fail", "platform-admin-fail@example.com"
        ),
        database_url=migrated_database_url,
    )
    with pytest.raises(RuntimeError, match="audit failed"):
        bundle.client.post(
            f"/api/v1/platform/users/{target.id}/suspend",
            json={"reason": "incident investigation"},
        )

    async def _verify():
        async with migrated_session_factory() as session:
            updated = await session.get(User, target.id)
            assert updated is not None
            assert updated.status == UserStatus.ACTIVE
            event = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.USER_SUSPENDED.value,
                        AuditEvent.target_id == target.id,
                    )
                )
            ).first()
            assert event is None

    run_async(_verify())


def test_suspend_user_keeps_external_transaction_open(
    migrated_session_factory,
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-admin-tx",
        email="platform-admin-tx@example.com",
    )
    target = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-target-user-tx",
        email="target-user-tx@example.com",
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                staff = await PlatformStaffRepository(session).get_by_user_id(admin.id)
                assert staff is not None
                actor = PlatformActor(
                    user=admin,
                    staff=staff,
                    permissions=frozenset(),
                )
                service = PlatformUsersService(session)
                assert session.in_transaction()
                await service.suspend_user(
                    user_id=target.id,
                    actor=actor,
                    reason="tx ownership",
                    audit_context=AuditContext(actor_user_id=admin.id),
                )
                assert session.in_transaction()

    run_async(_run())
