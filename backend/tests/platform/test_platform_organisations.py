import pytest

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.audit.services.audit_events import AuditEventService
from app.core.platform.permissions import PlatformRole
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.organisations.services.organisations import OrganisationService
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def _seed_platform_admin(session_factory, external_auth_id: str, email: str):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id, role=PlatformRole.PLATFORM_ADMIN.value
                )
            return user

    return run_async(_run())


def _seed_org(session_factory, *, name: str, slug: str):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                return await OrganisationService(session).create_organisation(
                    name=name, slug=slug
                )

    return run_async(_run())


def test_platform_org_suspend_restore_and_patch(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_admin(
        migrated_session_factory, "kc-po-admin", "po-admin@example.com"
    )
    org = _seed_org(migrated_session_factory, name="Acme", slug="acme")
    bundle = authenticated_client_factory(
        identity=identity_for("kc-po-admin", "po-admin@example.com"),
        database_url=migrated_database_url,
    )

    suspend = bundle.client.post(
        f"/api/v1/platform/organisations/{org.id}/suspend",
        json={"reason": "policy violation"},
    )
    assert suspend.status_code == 200

    async def _verify_suspend():
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert (
                updated is not None and updated.status == OrganisationStatus.SUSPENDED
            )
            event = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.ORGANISATION_SUSPENDED.value,
                        AuditEvent.target_id == org.id,
                    )
                )
            ).first()
            assert event is not None
            assert event._mapping["reason"] == "policy violation"

    run_async(_verify_suspend())

    restore = bundle.client.post(
        f"/api/v1/platform/organisations/{org.id}/restore",
        json={"reason": "issue resolved"},
    )
    assert restore.status_code == 200

    patch = bundle.client.patch(
        f"/api/v1/platform/organisations/{org.id}",
        json={"name": "New Name", "slug": "new-name", "reason": "correct typo"},
    )
    assert patch.status_code == 200

    async def _verify_restore_patch():
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert updated is not None
            assert updated.status == OrganisationStatus.ACTIVE
            assert updated.suspended_at is None and updated.suspended_reason is None
            assert updated.name == "New Name" and updated.slug == "new-name"
            restored = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.ORGANISATION_RESTORED.value,
                        AuditEvent.target_id == org.id,
                    )
                )
            ).first()
            patched = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.ORGANISATION_UPDATED.value,
                        AuditEvent.target_id == org.id,
                    )
                )
            ).first()
            assert (
                restored is not None and restored._mapping["reason"] == "issue resolved"
            )
            assert patched is not None and patched._mapping["reason"] == "correct typo"

    run_async(_verify_restore_patch())


def test_platform_org_negative_cases(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_admin(
        migrated_session_factory, "kc-po-admin2", "po-admin2@example.com"
    )
    org = _seed_org(migrated_session_factory, name="A", slug="a-org")
    _seed_org(migrated_session_factory, name="B", slug="b-org")
    bundle = authenticated_client_factory(
        identity=identity_for("kc-po-admin2", "po-admin2@example.com"),
        database_url=migrated_database_url,
    )

    assert (
        bundle.client.post(
            "/api/v1/platform/organisations/00000000-0000-0000-0000-000000000000/suspend",
            json={"reason": "x"},
        ).status_code
        == 404
    )
    assert (
        bundle.client.post(
            f"/api/v1/platform/organisations/{org.id}/restore", json={"reason": "x"}
        ).status_code
        == 409
    )
    assert (
        bundle.client.patch(
            f"/api/v1/platform/organisations/{org.id}",
            json={"name": "A", "slug": "a-org", "reason": "no change"},
        ).status_code
        == 409
    )
    assert (
        bundle.client.patch(
            f"/api/v1/platform/organisations/{org.id}",
            json={"slug": "INVALID SLUG", "reason": "x"},
        ).status_code
        == 422
    )
    assert (
        bundle.client.patch(
            f"/api/v1/platform/organisations/{org.id}",
            json={"slug": "b-org", "reason": "dup"},
        ).status_code
        == 409
    )


def test_platform_org_rollback_on_audit_failure(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
):
    _seed_platform_admin(
        migrated_session_factory, "kc-po-admin3", "po-admin3@example.com"
    )
    org = _seed_org(migrated_session_factory, name="Rollback", slug="rollback-org")

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditEventService, "record_event", _raise)
    bundle = authenticated_client_factory(
        identity=identity_for("kc-po-admin3", "po-admin3@example.com"),
        database_url=migrated_database_url,
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        bundle.client.post(
            f"/api/v1/platform/organisations/{org.id}/suspend",
            json={"reason": "incident"},
        )

    async def _verify():
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert updated is not None
            assert updated.status == OrganisationStatus.ACTIVE

    run_async(_verify())
