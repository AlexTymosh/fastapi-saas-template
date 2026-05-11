from __future__ import annotations

import pytest

from app.organisations.models.organisation import OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository
from app.platform.models.platform_staff import PlatformStaffRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


def _seed_platform_admin(session_factory):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for("kc-limited-admin", "limited-admin@example.com")
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=PlatformStaffRole.PLATFORM_ADMIN.value,
                )
            return user

    return run_async(_run())


def _seed_limited_view_data(session_factory):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user_service = UserService(session)
                alice = await user_service.provision_current_user(
                    identity_for("kc-limited-alice", "alice.safe-search@example.com")
                )
                alice.first_name = "Alice"
                alice.last_name = "Searchable"
                bob = await user_service.provision_current_user(
                    identity_for("kc-limited-bob", "bob.safe-search@example.com")
                )
                bob.first_name = "Bob"
                bob.status = UserStatus.SUSPENDED
                org_repo = OrganisationRepository(session)
                active_org = await org_repo.create(
                    name="Visible Limited Organisation",
                    slug="visible-limited-organisation",
                )
                suspended_org = await org_repo.create(
                    name="Suspended Limited Organisation",
                    slug="suspended-limited-organisation",
                )
                suspended_org.status = OrganisationStatus.SUSPENDED
                deleted_org = await org_repo.create(
                    name="Deleted Limited Organisation",
                    slug="deleted-limited-organisation",
                )
                await org_repo.soft_delete(deleted_org)
            return alice, bob, active_org, suspended_org, deleted_org

    return run_async(_run())


def _admin_client(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    admin = _seed_platform_admin(migrated_session_factory)
    return authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    ).client


def test_limited_users_support_status_search_and_pagination(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    alice, _bob, _active_org, _suspended_org, _deleted_org = _seed_limited_view_data(
        migrated_session_factory
    )
    client = _admin_client(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = client.get(
        "/api/v1/platform/users/limited",
        params={"q": "safe-search", "status": UserStatus.ACTIVE.value, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["limit"] == 1
    assert payload["meta"]["offset"] == 0
    assert payload["meta"]["total"] >= 1
    assert payload["data"][0]["id"] == str(alice.id)
    assert "email" not in payload["data"][0]


def test_limited_organisations_exclude_deleted_and_support_filters(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    _alice, _bob, _active_org, suspended_org, deleted_org = _seed_limited_view_data(
        migrated_session_factory
    )
    client = _admin_client(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = client.get(
        "/api/v1/platform/organisations/limited",
        params={
            "q": "limited-organisation",
            "status": OrganisationStatus.SUSPENDED.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    ids = {row["id"] for row in payload["data"]}
    assert str(suspended_org.id) in ids
    assert str(deleted_org.id) not in ids
    assert all("deleted_at" not in row for row in payload["data"])
