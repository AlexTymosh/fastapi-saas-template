from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditEvent
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError
from app.core.platform import PlatformActor, PlatformRole
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.platform.services.platform_staff import PlatformStaffService
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


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


def _actor(user, staff) -> PlatformActor:
    return PlatformActor(user=user, staff=staff, permissions=frozenset())


def _audit_context(user) -> AuditContext:
    return AuditContext(actor_user_id=user.id)


async def _audit_events_for_action(
    session, action: AuditAction, target_id=None
) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.action == action.value)
    if target_id is not None:
        stmt = stmt.where(AuditEvent.target_id == target_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _staff_count_for_user(session, user_id) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(PlatformStaff)
                .where(PlatformStaff.user_id == user_id)
            )
        ).scalar_one()
    )


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
        staff_env.regular_bundle.client.get(
            f"/api/v1/platform/staff/{staff_env.admin_staff.id}"
        ).status_code
        == 403
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
    assert create_response.status_code == 201
    created_staff_id = create_response.json()["id"]
    assert create_response.headers["Location"].endswith(
        f"/api/v1/platform/staff/{created_staff_id}"
    )
    detail_response = staff_env.admin_bundle.client.get(
        f"/api/v1/platform/staff/{created_staff_id}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == created_staff_id

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
        == 200
    )

    # Verify restore flow
    assert (
        staff_env.admin_bundle.client.post(
            f"/api/v1/platform/staff/{staff_env.support_staff.id}/restore",
            json={"reason": "policy done"},
        ).status_code
        == 200
    )

    # Verify redundant restores are idempotent.
    assert (
        staff_env.admin_bundle.client.post(
            f"/api/v1/platform/staff/{staff_env.support_staff.id}/restore",
            json={"reason": "again"},
        ).status_code
        == 200
    )


def test_cannot_demote_last_active_platform_admin(migrated_session_factory):
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-last-demote-actor",
        email="last-demote-actor@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    _, admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-last-demote-admin",
        email="last-demote-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                actor = PlatformActor(
                    user=actor_user,
                    staff=actor_staff,
                    permissions=frozenset(),
                )
                with pytest.raises(ConflictError, match="last active platform admin"):
                    await PlatformStaffService(session).change_role(
                        staff_id=admin_staff.id,
                        actor=actor,
                        role=PlatformStaffRole.SUPPORT_AGENT,
                        reason="regression",
                        audit_context=AuditContext(actor_user_id=actor_user.id),
                    )

    run_async(_run())


def test_cannot_suspend_last_active_platform_admin(migrated_session_factory):
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-last-suspend-actor",
        email="last-suspend-actor@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    _, admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-last-suspend-admin",
        email="last-suspend-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                actor = PlatformActor(
                    user=actor_user,
                    staff=actor_staff,
                    permissions=frozenset(),
                )
                with pytest.raises(ConflictError, match="last active platform admin"):
                    await PlatformStaffService(session).suspend_staff(
                        staff_id=admin_staff.id,
                        actor=actor,
                        reason="regression",
                        audit_context=AuditContext(actor_user_id=actor_user.id),
                    )

    run_async(_run())


def test_can_demote_platform_admin_when_another_active_admin_exists(
    staff_env, migrated_session_factory
):
    _, second_admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-second-admin-demote",
        email="second-admin-demote@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    response = staff_env.admin_bundle.client.patch(
        f"/api/v1/platform/staff/{second_admin_staff.id}/role",
        json={"role": "support_agent", "reason": "rotate admin duties"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == PlatformRole.SUPPORT_AGENT.value


def test_can_suspend_platform_admin_when_another_active_admin_exists(
    staff_env, migrated_session_factory
):
    _, second_admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-second-admin-suspend",
        email="second-admin-suspend@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    response = staff_env.admin_bundle.client.post(
        f"/api/v1/platform/staff/{second_admin_staff.id}/suspend",
        json={"reason": "rotate admin duties"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == PlatformStaffStatus.SUSPENDED.value


def test_platform_admin_demote_path_locks_active_admin_rows(
    staff_env, migrated_session_factory, monkeypatch
):
    _, second_admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-lock-admin-demote",
        email="lock-admin-demote@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    lock_calls = 0
    original_lock = PlatformStaffRepository.lock_active_platform_admins

    async def _counting_lock(self):
        nonlocal lock_calls
        lock_calls += 1
        return await original_lock(self)

    monkeypatch.setattr(
        PlatformStaffRepository, "lock_active_platform_admins", _counting_lock
    )

    response = staff_env.admin_bundle.client.patch(
        f"/api/v1/platform/staff/{second_admin_staff.id}/role",
        json={"role": "support_agent", "reason": "lock regression"},
    )

    assert response.status_code == 200
    assert lock_calls == 1


def test_lock_active_platform_admins_returns_only_active_admins(
    migrated_session_factory,
):
    _, active_admin = _seed_staff(
        migrated_session_factory,
        ext_id="kc-lock-active-admin",
        email="lock-active-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    _seed_staff(
        migrated_session_factory,
        ext_id="kc-lock-suspended-admin",
        email="lock-suspended-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
        status=PlatformStaffStatus.SUSPENDED,
    )
    _seed_staff(
        migrated_session_factory,
        ext_id="kc-lock-support",
        email="lock-support@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                # SQLite test databases do not enforce PostgreSQL row-lock semantics;
                # this regression covers the lock-aware query path and filtering.
                locked_admins = await PlatformStaffRepository(
                    session
                ).lock_active_platform_admins()
                assert [admin.id for admin in locked_admins] == [active_admin.id]

    run_async(_run())


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


@pytest.mark.audit
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


def test_platform_staff_service_admin_can_create_staff_with_audit(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-create-admin",
        email="service-create-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target = _seed_user(
        migrated_session_factory,
        ext_id="kc-service-create-target",
        email="service-create-target@example.com",
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                staff = await PlatformStaffService(session).create_staff(
                    actor=_actor(actor_user, actor_staff),
                    user_id=target.id,
                    role=PlatformStaffRole.SUPPORT_AGENT,
                    reason="support coverage",
                    audit_context=_audit_context(actor_user),
                )
                assert staff.role == PlatformStaffRole.SUPPORT_AGENT.value
                assert staff.created_by_user_id == actor_user.id

            events = await _audit_events_for_action(
                session, AuditAction.PLATFORM_STAFF_CREATED, target_id=staff.id
            )
            event = next(event for event in events if event.target_id == staff.id)
            assert event.metadata_json == {
                "user_id": str(target.id),
                "role": PlatformStaffRole.SUPPORT_AGENT.value,
            }

    run_async(_run())


def test_platform_staff_service_cannot_create_duplicate_staff(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-duplicate-admin",
        email="service-duplicate-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target_user, _ = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-duplicate-target",
        email="service-duplicate-target@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                with pytest.raises(ConflictError, match="already exists"):
                    await PlatformStaffService(session).create_staff(
                        actor=_actor(actor_user, actor_staff),
                        user_id=target_user.id,
                        role=PlatformStaffRole.COMPLIANCE_OFFICER,
                        reason="duplicate",
                        audit_context=_audit_context(actor_user),
                    )
                assert await _staff_count_for_user(session, target_user.id) == 1

    run_async(_run())


def test_platform_staff_service_cannot_create_staff_for_suspended_user(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-suspended-admin",
        email="service-suspended-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target = _seed_user(
        migrated_session_factory,
        ext_id="kc-service-suspended-target",
        email="service-suspended-target@example.com",
        status=UserStatus.SUSPENDED,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                with pytest.raises(ConflictError, match="User is not active"):
                    await PlatformStaffService(session).create_staff(
                        actor=_actor(actor_user, actor_staff),
                        user_id=target.id,
                        role=PlatformStaffRole.SUPPORT_AGENT,
                        reason="inactive",
                        audit_context=_audit_context(actor_user),
                    )
                assert await _staff_count_for_user(session, target.id) == 0

    run_async(_run())


def test_platform_staff_service_cannot_demote_own_platform_admin_role(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-self-demote",
        email="service-self-demote@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                with pytest.raises(ConflictError, match="Cannot demote own"):
                    await PlatformStaffService(session).change_role(
                        staff_id=actor_staff.id,
                        actor=_actor(actor_user, actor_staff),
                        role=PlatformStaffRole.SUPPORT_AGENT,
                        reason="self demote",
                        audit_context=_audit_context(actor_user),
                    )
                staff = await PlatformStaffRepository(session).get_by_id(actor_staff.id)
                assert staff is not None
                assert staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
                assert not await _audit_events_for_action(
                    session,
                    AuditAction.PLATFORM_STAFF_ROLE_CHANGED,
                    target_id=actor_staff.id,
                )

    run_async(_run())


def test_platform_staff_service_cannot_demote_last_active_platform_admin_with_no_audit(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-last-demote-actor",
        email="service-last-demote-actor@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    _, admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-last-demote-admin",
        email="service-last-demote-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                with pytest.raises(
                    ConflictError, match="Cannot demote last active platform admin"
                ):
                    await PlatformStaffService(session).change_role(
                        staff_id=admin_staff.id,
                        actor=_actor(actor_user, actor_staff),
                        role=PlatformStaffRole.SUPPORT_AGENT,
                        reason="last admin",
                        audit_context=_audit_context(actor_user),
                    )
                staff = await PlatformStaffRepository(session).get_by_id(admin_staff.id)
                assert staff is not None
                assert staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
                assert not await _audit_events_for_action(
                    session,
                    AuditAction.PLATFORM_STAFF_ROLE_CHANGED,
                    target_id=admin_staff.id,
                )

    run_async(_run())


def test_platform_staff_service_can_demote_admin_with_another_admin_with_audit(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-demote-actor",
        email="service-demote-actor@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target_user, target_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-demote-target",
        email="service-demote-target@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                staff = await PlatformStaffService(session).change_role(
                    staff_id=target_staff.id,
                    actor=_actor(actor_user, actor_staff),
                    role=PlatformStaffRole.SUPPORT_AGENT,
                    reason="rotate",
                    audit_context=_audit_context(actor_user),
                )
                assert staff.role == PlatformStaffRole.SUPPORT_AGENT.value

            events = await _audit_events_for_action(
                session,
                AuditAction.PLATFORM_STAFF_ROLE_CHANGED,
                target_id=target_staff.id,
            )
            event = next(
                event for event in events if event.target_id == target_staff.id
            )
            assert event.metadata_json == {
                "old_role": PlatformStaffRole.PLATFORM_ADMIN.value,
                "new_role": PlatformStaffRole.SUPPORT_AGENT.value,
                "target_user_id": str(target_user.id),
            }

    run_async(_run())


def test_platform_staff_service_cannot_suspend_own_record_with_no_audit(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-self-suspend",
        email="service-self-suspend@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                with pytest.raises(ConflictError, match="Cannot suspend own"):
                    await PlatformStaffService(session).suspend_staff(
                        staff_id=actor_staff.id,
                        actor=_actor(actor_user, actor_staff),
                        reason="self suspend",
                        audit_context=_audit_context(actor_user),
                    )
                staff = await PlatformStaffRepository(session).get_by_id(actor_staff.id)
                assert staff is not None
                assert staff.status == PlatformStaffStatus.ACTIVE.value
                assert not await _audit_events_for_action(
                    session,
                    AuditAction.PLATFORM_STAFF_SUSPENDED,
                    target_id=actor_staff.id,
                )

    run_async(_run())


def test_platform_staff_service_cannot_suspend_last_active_platform_admin_with_no_audit(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-last-suspend-actor",
        email="service-last-suspend-actor@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    _, admin_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-last-suspend-admin",
        email="service-last-suspend-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                with pytest.raises(
                    ConflictError, match="Cannot suspend last active platform admin"
                ):
                    await PlatformStaffService(session).suspend_staff(
                        staff_id=admin_staff.id,
                        actor=_actor(actor_user, actor_staff),
                        reason="last admin",
                        audit_context=_audit_context(actor_user),
                    )
                staff = await PlatformStaffRepository(session).get_by_id(admin_staff.id)
                assert staff is not None
                assert staff.status == PlatformStaffStatus.ACTIVE.value
                assert not await _audit_events_for_action(
                    session,
                    AuditAction.PLATFORM_STAFF_SUSPENDED,
                    target_id=admin_staff.id,
                )

    run_async(_run())


def test_platform_staff_service_can_suspend_admin_with_another_admin_with_audit(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-suspend-actor",
        email="service-suspend-actor@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target_user, target_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-suspend-target",
        email="service-suspend-target@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                staff = await PlatformStaffService(session).suspend_staff(
                    staff_id=target_staff.id,
                    actor=_actor(actor_user, actor_staff),
                    reason="policy",
                    audit_context=_audit_context(actor_user),
                )
                assert staff.status == PlatformStaffStatus.SUSPENDED.value
                assert staff.suspended_at is not None
                assert staff.suspended_reason == "policy"

            events = await _audit_events_for_action(
                session, AuditAction.PLATFORM_STAFF_SUSPENDED, target_id=target_staff.id
            )
            event = next(
                event for event in events if event.target_id == target_staff.id
            )
            assert event.metadata_json == {
                "target_user_id": str(target_user.id),
                "role": PlatformStaffRole.PLATFORM_ADMIN.value,
            }

    run_async(_run())


def test_platform_staff_service_can_restore_suspended_staff_with_audit(
    migrated_session_factory,
) -> None:
    actor_user, _ = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-restore-actor",
        email="service-restore-actor@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target_user, target_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-restore-target",
        email="service-restore-target@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
        status=PlatformStaffStatus.SUSPENDED,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                staff = await PlatformStaffRepository(session).get_by_id(
                    target_staff.id
                )
                assert staff is not None
                staff.suspended_reason = "old"
                staff.suspended_at = staff.created_at

            async with session.begin():
                staff = await PlatformStaffService(session).restore_staff(
                    staff_id=target_staff.id,
                    reason="resolved",
                    audit_context=_audit_context(actor_user),
                )
                assert staff.status == PlatformStaffStatus.ACTIVE.value
                assert staff.suspended_at is None
                assert staff.suspended_reason is None

            events = await _audit_events_for_action(
                session, AuditAction.PLATFORM_STAFF_RESTORED, target_id=target_staff.id
            )
            event = next(
                event for event in events if event.target_id == target_staff.id
            )
            assert event.metadata_json == {
                "target_user_id": str(target_user.id),
                "role": PlatformStaffRole.SUPPORT_AGENT.value,
            }

    run_async(_run())


def test_platform_staff_service_restore_active_staff_is_idempotent_without_audit(
    migrated_session_factory,
) -> None:
    actor_user, _ = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-active-restore-actor",
        email="service-active-restore-actor@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    _, target_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-active-restore-target",
        email="service-active-restore-target@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                restored = await PlatformStaffService(session).restore_staff(
                    staff_id=target_staff.id,
                    reason="already",
                    audit_context=_audit_context(actor_user),
                )
                assert restored.status == PlatformStaffStatus.ACTIVE.value
                staff = await PlatformStaffRepository(session).get_by_id(
                    target_staff.id
                )
                assert staff is not None
                assert staff.status == PlatformStaffStatus.ACTIVE.value
                assert not await _audit_events_for_action(
                    session,
                    AuditAction.PLATFORM_STAFF_RESTORED,
                    target_id=target_staff.id,
                )

    run_async(_run())


@pytest.mark.audit
def test_platform_staff_create_rolls_back_on_audit_failure(
    migrated_session_factory, monkeypatch
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-create-rollback-admin",
        email="service-create-rollback-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target = _seed_user(
        migrated_session_factory,
        ext_id="kc-service-create-rollback-target",
        email="service-create-rollback-target@example.com",
    )

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditEventService, "record_event", _raise)

    async def _run():
        with pytest.raises(RuntimeError, match="audit failed"):
            async with migrated_session_factory() as session:
                async with session.begin():
                    await PlatformStaffService(session).create_staff(
                        actor=_actor(actor_user, actor_staff),
                        user_id=target.id,
                        role=PlatformStaffRole.SUPPORT_AGENT,
                        reason="rollback",
                        audit_context=_audit_context(actor_user),
                    )

        async with migrated_session_factory() as session:
            assert await _staff_count_for_user(session, target.id) == 0

    run_async(_run())


@pytest.mark.audit
def test_platform_staff_change_role_rolls_back_on_audit_failure(
    migrated_session_factory, monkeypatch
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-role-rollback-admin",
        email="service-role-rollback-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    _, target_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-role-rollback-target",
        email="service-role-rollback-target@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditEventService, "record_event", _raise)

    async def _run():
        with pytest.raises(RuntimeError, match="audit failed"):
            async with migrated_session_factory() as session:
                async with session.begin():
                    await PlatformStaffService(session).change_role(
                        staff_id=target_staff.id,
                        actor=_actor(actor_user, actor_staff),
                        role=PlatformStaffRole.COMPLIANCE_OFFICER,
                        reason="rollback",
                        audit_context=_audit_context(actor_user),
                    )

        async with migrated_session_factory() as session:
            staff = await PlatformStaffRepository(session).get_by_id(target_staff.id)
            assert staff is not None
            assert staff.role == PlatformStaffRole.SUPPORT_AGENT.value

    run_async(_run())


@pytest.mark.audit
def test_platform_staff_suspend_rolls_back_on_audit_failure(
    migrated_session_factory, monkeypatch
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-suspend-rollback-admin",
        email="service-suspend-rollback-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    _, target_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-suspend-rollback-target",
        email="service-suspend-rollback-target@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditEventService, "record_event", _raise)

    async def _run():
        with pytest.raises(RuntimeError, match="audit failed"):
            async with migrated_session_factory() as session:
                async with session.begin():
                    await PlatformStaffService(session).suspend_staff(
                        staff_id=target_staff.id,
                        actor=_actor(actor_user, actor_staff),
                        reason="rollback",
                        audit_context=_audit_context(actor_user),
                    )

        async with migrated_session_factory() as session:
            staff = await PlatformStaffRepository(session).get_by_id(target_staff.id)
            assert staff is not None
            assert staff.status == PlatformStaffStatus.ACTIVE.value
            assert staff.suspended_at is None
            assert staff.suspended_reason is None

    run_async(_run())


def test_platform_staff_service_keeps_external_transaction_open(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-staff-tx-admin",
        email="service-staff-tx-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    target = _seed_user(
        migrated_session_factory,
        ext_id="kc-service-staff-tx-target",
        email="service-staff-tx-target@example.com",
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                service = PlatformStaffService(session)
                assert session.in_transaction()
                await service.create_staff(
                    actor=_actor(actor_user, actor_staff),
                    user_id=target.id,
                    role=PlatformStaffRole.SUPPORT_AGENT,
                    reason="tx ownership",
                    audit_context=_audit_context(actor_user),
                )
                assert session.in_transaction()

    run_async(_run())


@pytest.mark.audit
def test_platform_staff_service_suspend_suspended_staff_is_idempotent_without_audit(
    migrated_session_factory,
) -> None:
    actor_user, actor_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-idem-suspend-actor",
        email="service-idem-suspend-actor@example.com",
        role=PlatformRole.PLATFORM_ADMIN.value,
    )
    _, target_staff = _seed_staff(
        migrated_session_factory,
        ext_id="kc-service-idem-suspend-target",
        email="service-idem-suspend-target@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
        status=PlatformStaffStatus.SUSPENDED,
    )

    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                staff = await PlatformStaffRepository(session).get_by_id(
                    target_staff.id
                )
                assert staff is not None
                staff.suspended_reason = "original reason"
                staff.suspended_at = staff.created_at

            async with session.begin():
                service = PlatformStaffService(session)
                staff = await service.suspend_staff(
                    staff_id=target_staff.id,
                    actor=_actor(actor_user, actor_staff),
                    reason="new reason",
                    audit_context=_audit_context(actor_user),
                )
                assert staff.status == PlatformStaffStatus.SUSPENDED.value
                assert staff.suspended_reason == "original reason"
                assert staff.suspended_at == staff.created_at
                assert not await _audit_events_for_action(
                    session,
                    AuditAction.PLATFORM_STAFF_SUSPENDED,
                    target_id=target_staff.id,
                )

    run_async(_run())
