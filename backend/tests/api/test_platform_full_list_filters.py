import pytest

from app.core.platform.permissions import PlatformRole
from app.organisations.models.organisation import OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


def _seed_platform_actor(session_factory, *, external_auth_id: str, role: PlatformRole):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, f"{external_auth_id}@example.com")
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
            return user

    return run_async(_run())


def _seed_full_list_data(session_factory):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                alpha_user = await UserService(session).provision_current_user(
                    identity_for("kc-full-alpha", "alpha.full-list@example.com")
                )
                alpha_user.first_name = "Alpha"
                alpha_user.last_name = "Visible"

                beta_user = await UserService(session).provision_current_user(
                    identity_for("kc-full-beta", "beta.full-list@example.com")
                )
                beta_user.first_name = "Beta"
                beta_user.last_name = "Hidden"
                beta_user.status = UserStatus.SUSPENDED

                gamma_user = await UserService(session).provision_current_user(
                    identity_for("kc-full-gamma", "gamma.full-list@example.com")
                )
                gamma_user.first_name = "Gamma"
                gamma_user.last_name = "Searchable"

                alpha_org = await OrganisationRepository(session).create(
                    name="Alpha Full Organisation",
                    slug="alpha-full-org",
                )
                beta_org = await OrganisationRepository(session).create(
                    name="Beta Full Organisation",
                    slug="beta-full-org",
                )
                beta_org.status = OrganisationStatus.SUSPENDED
                deleted_org = await OrganisationRepository(session).create(
                    name="Deleted Full Organisation",
                    slug="deleted-full-org",
                )
                await OrganisationRepository(session).soft_delete(deleted_org)

                support_staff = await PlatformStaffRepository(session).create_staff(
                    user_id=gamma_user.id,
                    role=PlatformStaffRole.SUPPORT_AGENT.value,
                )
                compliance_staff = await PlatformStaffRepository(session).create_staff(
                    user_id=beta_user.id,
                    role=PlatformStaffRole.COMPLIANCE_OFFICER.value,
                )
                compliance_staff.status = PlatformStaffStatus.SUSPENDED.value
                await session.flush()
            return {
                "alpha_user_id": str(alpha_user.id),
                "beta_user_id": str(beta_user.id),
                "gamma_user_id": str(gamma_user.id),
                "alpha_org_id": str(alpha_org.id),
                "beta_org_id": str(beta_org.id),
                "deleted_org_id": str(deleted_org.id),
                "support_staff_id": str(support_staff.id),
                "compliance_staff_id": str(compliance_staff.id),
            }

    return run_async(_run())


def _platform_admin_bundle(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    actor = _seed_platform_actor(
        migrated_session_factory,
        external_auth_id="kc-full-list-admin",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    return authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )


def test_full_users_list_filters_by_status(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    seeded = _seed_full_list_data(migrated_session_factory)
    bundle = _platform_admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/users", params={"status": "suspended"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert [row["id"] for row in payload["data"]] == [seeded["beta_user_id"]]


def test_full_users_list_searches_by_email_and_name(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    seeded = _seed_full_list_data(migrated_session_factory)
    bundle = _platform_admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    email_response = bundle.client.get(
        "/api/v1/platform/users", params={"q": "alpha.full-list@example.com"}
    )
    name_response = bundle.client.get("/api/v1/platform/users", params={"q": "search"})

    assert email_response.status_code == 200
    assert email_response.json()["meta"]["total"] == 1
    assert email_response.json()["data"][0]["id"] == seeded["alpha_user_id"]
    assert name_response.status_code == 200
    assert name_response.json()["meta"]["total"] == 1
    assert name_response.json()["data"][0]["id"] == seeded["gamma_user_id"]


def test_full_organisations_list_filters_by_status(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    seeded = _seed_full_list_data(migrated_session_factory)
    bundle = _platform_admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/organisations", params={"status": "suspended"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert [row["id"] for row in payload["data"]] == [seeded["beta_org_id"]]


def test_full_organisations_list_searches_by_name_and_slug(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    seeded = _seed_full_list_data(migrated_session_factory)
    bundle = _platform_admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    name_response = bundle.client.get(
        "/api/v1/platform/organisations", params={"q": "alpha full"}
    )
    slug_response = bundle.client.get(
        "/api/v1/platform/organisations", params={"q": "deleted-full-org"}
    )

    assert name_response.status_code == 200
    assert name_response.json()["meta"]["total"] == 1
    assert name_response.json()["data"][0]["id"] == seeded["alpha_org_id"]
    assert slug_response.status_code == 200
    assert slug_response.json()["meta"]["total"] == 1
    assert slug_response.json()["data"][0]["id"] == seeded["deleted_org_id"]


def test_full_platform_staff_list_filters_by_status(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    seeded = _seed_full_list_data(migrated_session_factory)
    bundle = _platform_admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/staff", params={"status": "suspended"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert [row["id"] for row in payload["data"]] == [seeded["compliance_staff_id"]]


def test_full_platform_staff_list_filters_by_role(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    seeded = _seed_full_list_data(migrated_session_factory)
    bundle = _platform_admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/staff", params={"role": "support_agent"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert [row["id"] for row in payload["data"]] == [seeded["support_staff_id"]]


def test_full_users_list_pagination_metadata_and_ordering_are_stable(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_full_list_data(migrated_session_factory)
    bundle = _platform_admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/users", params={"limit": 2, "offset": 1}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"] == {"total": 4, "limit": 2, "offset": 1}
    created_and_ids = [(row["created_at"], row["id"]) for row in payload["data"]]
    assert created_and_ids == sorted(created_and_ids, reverse=True)


@pytest.mark.parametrize(
    "role", [PlatformRole.SUPPORT_AGENT, PlatformRole.COMPLIANCE_OFFICER]
)
def test_limited_roles_cannot_access_full_lists_with_filters(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    role: PlatformRole,
) -> None:
    _seed_full_list_data(migrated_session_factory)
    actor = _seed_platform_actor(
        migrated_session_factory,
        external_auth_id=f"kc-full-list-denied-{role.value}",
        role=role,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    responses = [
        bundle.client.get("/api/v1/platform/users", params={"q": "alpha"}),
        bundle.client.get(
            "/api/v1/platform/organisations", params={"status": "active"}
        ),
        bundle.client.get("/api/v1/platform/staff", params={"role": "support_agent"}),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
