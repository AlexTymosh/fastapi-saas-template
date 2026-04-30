import pytest

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.audit.services.audit_events import AuditEventService
from app.core.platform.permissions import PlatformRole
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
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


def _seed_organisation(session_factory, *, name: str, slug: str) -> Organisation:
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                org = Organisation(name=name, slug=slug)
                session.add(org)
            return org

    return run_async(_run())


def test_platform_admin_can_suspend_organisation(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-suspend",
        email="platform-org-suspend@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Acme", slug="acme")

    bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-platform-org-suspend", "platform-org-suspend@example.com"
        ),
        database_url=migrated_database_url,
    )
    response = bundle.client.post(
        f"/api/v1/platform/organisations/{org.id}/suspend",
        json={"reason": "compliance incident"},
    )
    assert response.status_code == 200

    async def _verify():
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert updated is not None
            assert updated.status == OrganisationStatus.SUSPENDED
            event = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.ORGANISATION_SUSPENDED.value,
                        AuditEvent.target_id == org.id,
                    )
                )
            ).first()
            assert event is not None
            assert event._mapping["reason"] == "compliance incident"

    run_async(_verify())


def test_platform_admin_can_restore_suspended_organisation(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-restore",
        email="platform-org-restore@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Bravo", slug="bravo")

    async def _suspend():
        async with migrated_session_factory() as session:
            async with session.begin():
                db_org = await session.get(Organisation, org.id)
                assert db_org is not None
                db_org.status = OrganisationStatus.SUSPENDED
                db_org.suspended_reason = "seed"

    run_async(_suspend())

    bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-platform-org-restore", "platform-org-restore@example.com"
        ),
        database_url=migrated_database_url,
    )
    response = bundle.client.post(
        f"/api/v1/platform/organisations/{org.id}/restore",
        json={"reason": "issue resolved"},
    )
    assert response.status_code == 200

    async def _verify():
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert updated is not None
            assert updated.status == OrganisationStatus.ACTIVE
            assert updated.suspended_at is None
            assert updated.suspended_reason is None
            event = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.ORGANISATION_RESTORED.value,
                        AuditEvent.target_id == org.id,
                    )
                )
            ).first()
            assert event is not None
            assert event._mapping["reason"] == "issue resolved"

    run_async(_verify())


def test_suspend_missing_organisation_returns_404(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-404",
        email="platform-org-404@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.post(
        "/api/v1/platform/organisations/00000000-0000-0000-0000-000000000001/suspend",
        json={"reason": "reason"},
    )
    assert response.status_code == 404


def test_restore_active_organisation_returns_409(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-active",
        email="platform-org-active@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Charlie", slug="charlie")
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.post(
        f"/api/v1/platform/organisations/{org.id}/restore",
        json={"reason": "reason"},
    )
    assert response.status_code == 409


def test_platform_org_correction_updates_and_audits(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-patch",
        email="platform-org-patch@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Delta", slug="delta")

    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.patch(
        f"/api/v1/platform/organisations/{org.id}",
        json={"name": "New Name", "slug": "new-slug", "reason": "correct typo"},
    )
    assert response.status_code == 200

    async def _verify():
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert updated is not None
            assert updated.name == "New Name"
            assert updated.slug == "new-slug"
            event = (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.action == AuditAction.ORGANISATION_UPDATED.value,
                        AuditEvent.target_id == org.id,
                    )
                )
            ).first()
            assert event is not None
            assert event._mapping["reason"] == "correct typo"

    run_async(_verify())


def test_platform_org_correction_duplicate_slug_returns_409(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-dup",
        email="platform-org-dup@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Echo", slug="echo")
    _seed_organisation(migrated_session_factory, name="Foxtrot", slug="foxtrot")
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.patch(
        f"/api/v1/platform/organisations/{org.id}",
        json={"slug": "foxtrot", "reason": "sync"},
    )
    assert response.status_code == 409


def test_platform_org_correction_invalid_slug_returns_422(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-invalid-slug",
        email="platform-org-invalid-slug@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Golf", slug="golf")
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.patch(
        f"/api/v1/platform/organisations/{org.id}",
        json={"slug": "INVALID SLUG", "reason": "sync"},
    )
    assert response.status_code == 422


def test_platform_org_correction_no_actual_change_returns_409(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-no-change",
        email="platform-org-no-change@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Hotel", slug="hotel")
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.patch(
        f"/api/v1/platform/organisations/{org.id}",
        json={"name": "Hotel", "slug": "hotel", "reason": "sync"},
    )
    assert response.status_code == 409


def test_platform_org_suspend_rolls_back_on_audit_failure(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    admin = _seed_platform_admin(
        migrated_session_factory,
        external_auth_id="kc-platform-org-audit-fail",
        email="platform-org-audit-fail@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="India", slug="india")

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditEventService, "record_event", _raise)

    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
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
