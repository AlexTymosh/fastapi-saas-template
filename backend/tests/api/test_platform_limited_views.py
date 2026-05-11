import pytest

from app.core.platform.permissions import PlatformRole
from app.organisations.models.organisation import OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository
from app.platform.models.platform_staff import PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


def _seed_staff(
    session_factory, *, external_auth_id: str, email: str, role: PlatformRole
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
                staff.status = PlatformStaffStatus.ACTIVE.value
                await session.flush()
            return user

    return run_async(_run())


def _seed_limited_view_data(session_factory):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                alpha = await UserService(session).provision_current_user(
                    identity_for("kc-alpha", "alpha.full@example.com")
                )
                alpha.first_name = "Alpha"
                alpha.last_name = "Visible"
                beta = await UserService(session).provision_current_user(
                    identity_for("kc-beta", "beta.full@example.com")
                )
                beta.first_name = "Beta"
                beta.last_name = "Hidden"
                beta.status = UserStatus.SUSPENDED
                beta.suspended_reason = "sensitive reason"

                active_org = await OrganisationRepository(session).create(
                    name="Alpha Organisation",
                    slug="alpha-org",
                )
                suspended_org = await OrganisationRepository(session).create(
                    name="Beta Organisation",
                    slug="beta-org",
                )
                suspended_org.status = OrganisationStatus.SUSPENDED
                suspended_org.suspended_reason = "sensitive org reason"
                deleted_org = await OrganisationRepository(session).create(
                    name="Deleted Organisation",
                    slug="deleted-org",
                )
                await OrganisationRepository(session).soft_delete(deleted_org)
                await session.flush()
            return alpha.id, beta.id, active_org.id, suspended_org.id, deleted_org.id

    return run_async(_run())


def test_limited_platform_users_support_agent_can_filter_by_name_without_full_email(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_limited_view_data(migrated_session_factory)
    actor = _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-support-limited-users",
        email="support-limited-users@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get(
        "/api/v1/platform/users/limited",
        params={"q": "visible", "status": "active"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert payload["data"][0]["first_name"] == "Alpha"
    assert "email" not in payload["data"][0]
    assert "email_verified" not in payload["data"][0]
    assert "suspended_reason" not in payload["data"][0]
    assert "alpha.full@example.com" not in response.text


def test_limited_platform_users_q_does_not_match_hidden_email(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_limited_view_data(migrated_session_factory)
    actor = _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-support-limited-email-q",
        email="support-limited-email-q@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get(
        "/api/v1/platform/users/limited",
        params={"q": "alpha.full@example.com", "status": "active"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 0
    assert payload["data"] == []
    assert "alpha.full@example.com" not in response.text


def test_limited_platform_users_exact_email_uses_exact_lookup_without_exposure(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_limited_view_data(migrated_session_factory)
    actor = _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-support-limited-exact-email",
        email="support-limited-exact-email@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    partial_response = bundle.client.get(
        "/api/v1/platform/users/limited",
        params={"exact_email": "alpha.full@example.net"},
    )
    exact_response = bundle.client.get(
        "/api/v1/platform/users/limited",
        params={"exact_email": "ALPHA.FULL@EXAMPLE.COM"},
    )
    combined_response = bundle.client.get(
        "/api/v1/platform/users/limited",
        params={
            "status": "active",
            "q": "visible",
            "exact_email": "alpha.full@example.com",
        },
    )

    assert partial_response.status_code == 200
    partial_payload = partial_response.json()
    assert partial_payload["meta"]["total"] == 0
    assert partial_payload["data"] == []
    assert exact_response.status_code == 200
    exact_payload = exact_response.json()
    assert exact_payload["meta"]["total"] == 1
    assert exact_payload["data"][0]["first_name"] == "Alpha"
    assert "email" not in exact_payload["data"][0]
    assert "alpha.full@example.com" not in exact_response.text

    assert combined_response.status_code == 200
    combined_payload = combined_response.json()
    assert combined_payload["meta"]["total"] == 1
    assert combined_payload["data"][0]["first_name"] == "Alpha"


def test_limited_platform_organisations_support_agent_excludes_deleted_orgs(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_limited_view_data(migrated_session_factory)
    actor = _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-support-limited-orgs",
        email="support-limited-orgs@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/organisations/limited")

    assert response.status_code == 200
    names = {row["name"] for row in response.json()["data"]}
    assert "Alpha Organisation" in names
    assert "Beta Organisation" in names
    assert "Deleted Organisation" not in names


def test_limited_platform_organisations_status_and_search_filters(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_limited_view_data(migrated_session_factory)
    actor = _seed_staff(
        migrated_session_factory,
        external_auth_id="kc-compliance-limited-orgs",
        email="compliance-limited-orgs@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get(
        "/api/v1/platform/organisations/limited",
        params={"q": "beta", "status": "suspended"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert payload["data"][0]["slug"] == "beta-org"
