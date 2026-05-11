from datetime import UTC, datetime, timedelta

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


def _seed_platform_staff(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    role: PlatformRole,
    status: PlatformStaffStatus = PlatformStaffStatus.ACTIVE,
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
                staff.status = status.value
                await session.flush()
            return user, staff

    return run_async(_run())


def _seed_full_list_data(session_factory):
    base_time = datetime(2026, 1, 1, tzinfo=UTC)

    async def _run():
        async with session_factory() as session:
            async with session.begin():
                alpha = await UserService(session).provision_current_user(
                    identity_for(
                        "kc-full-filter-alpha", "alpha.needle.activefilter@example.com"
                    )
                )
                alpha.first_name = "AlphaNeedle"
                alpha.last_name = "Visible"
                alpha.status = UserStatus.ACTIVE
                alpha.created_at = base_time + timedelta(minutes=2)

                beta = await UserService(session).provision_current_user(
                    identity_for("kc-full-filter-beta", "beta.full@example.com")
                )
                beta.first_name = "Beta"
                beta.last_name = "NeedleSurname"
                beta.status = UserStatus.SUSPENDED
                beta.created_at = base_time + timedelta(minutes=2)

                gamma = await UserService(session).provision_current_user(
                    identity_for(
                        "kc-full-filter-gamma", "gamma.activefilter@example.com"
                    )
                )
                gamma.first_name = "Gamma"
                gamma.last_name = "Other"
                gamma.status = UserStatus.ACTIVE
                gamma.created_at = base_time

                active_org = await OrganisationRepository(session).create(
                    name="Needle Alpha Organisation",
                    slug="alpha-filter-org",
                )
                active_org.status = OrganisationStatus.ACTIVE
                active_org.created_at = base_time + timedelta(minutes=2)

                suspended_org = await OrganisationRepository(session).create(
                    name="Beta Organisation",
                    slug="needle-beta-org",
                )
                suspended_org.status = OrganisationStatus.SUSPENDED
                suspended_org.created_at = base_time + timedelta(minutes=2)

                deleted_org = await OrganisationRepository(session).create(
                    name="Needle Deleted Organisation",
                    slug="needle-deleted-org",
                )
                deleted_org.status = OrganisationStatus.ACTIVE
                deleted_org.created_at = base_time + timedelta(minutes=1)
                await OrganisationRepository(session).soft_delete(deleted_org)

                await session.flush()
            return {
                "alpha_user_id": str(alpha.id),
                "beta_user_id": str(beta.id),
                "gamma_user_id": str(gamma.id),
                "active_org_id": str(active_org.id),
                "suspended_org_id": str(suspended_org.id),
                "deleted_org_id": str(deleted_org.id),
            }

    return run_async(_run())


def _admin_bundle(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-full-filter-admin",
        email="full-filter-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    return authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )


def test_full_users_list_filters_by_status_and_keeps_pagination_metadata(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    ids = _seed_full_list_data(migrated_session_factory)
    bundle = _admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/users",
        params={"status": "active", "q": "activefilter", "limit": 1, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"] == {"total": 2, "limit": 1, "offset": 0}
    assert len(payload["data"]) == 1
    assert payload["data"][0]["id"] == ids["alpha_user_id"]
    assert payload["data"][0]["status"] == "active"


def test_full_users_list_searches_by_email_and_name(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    ids = _seed_full_list_data(migrated_session_factory)
    bundle = _admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/users", params={"q": "needle", "limit": 10}
    )

    assert response.status_code == 200
    payload = response.json()
    returned_ids = [row["id"] for row in payload["data"]]
    assert payload["meta"]["total"] == 2
    assert returned_ids == sorted(
        [ids["alpha_user_id"], ids["beta_user_id"]], reverse=True
    )
    assert ids["gamma_user_id"] not in returned_ids


def test_full_organisations_list_filters_by_status_and_keeps_deleted_visibility(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    ids = _seed_full_list_data(migrated_session_factory)
    bundle = _admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/organisations",
        params={"status": "active", "q": "needle", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    returned_ids = [row["id"] for row in payload["data"]]
    assert payload["meta"]["total"] == 2
    assert ids["active_org_id"] in returned_ids
    assert ids["deleted_org_id"] in returned_ids
    assert ids["suspended_org_id"] not in returned_ids


def test_full_organisations_list_searches_by_name_and_slug(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    ids = _seed_full_list_data(migrated_session_factory)
    bundle = _admin_bundle(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = bundle.client.get(
        "/api/v1/platform/organisations", params={"q": "needle", "limit": 10}
    )

    assert response.status_code == 200
    payload = response.json()
    returned_ids = [row["id"] for row in payload["data"]]
    assert payload["meta"]["total"] == 3
    assert ids["active_org_id"] in returned_ids
    assert ids["suspended_org_id"] in returned_ids
    assert ids["deleted_org_id"] in returned_ids


def test_full_platform_staff_list_filters_by_status_and_role(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-staff-filter-admin",
        email="staff-filter-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    active_support, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-staff-filter-support-active",
        email="staff-filter-support-active@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    suspended_support, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-staff-filter-support-suspended",
        email="staff-filter-support-suspended@example.com",
        role=PlatformRole.SUPPORT_AGENT,
        status=PlatformStaffStatus.SUSPENDED,
    )
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-staff-filter-compliance",
        email="staff-filter-compliance@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )

    status_response = bundle.client.get(
        "/api/v1/platform/staff", params={"status": "suspended"}
    )
    role_response = bundle.client.get(
        "/api/v1/platform/staff", params={"role": "support_agent", "limit": 10}
    )

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["meta"]["total"] == 1
    assert status_payload["data"][0]["user_id"] == str(suspended_support.id)

    assert role_response.status_code == 200
    role_payload = role_response.json()
    assert role_payload["meta"]["total"] == 2
    assert {row["user_id"] for row in role_payload["data"]} == {
        str(active_support.id),
        str(suspended_support.id),
    }


def test_full_list_filters_do_not_grant_access_to_limited_platform_roles(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_full_list_data(migrated_session_factory)
    support, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-full-filter-support",
        email="full-filter-support@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    compliance, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-full-filter-compliance",
        email="full-filter-compliance@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )
    support_bundle = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
    )
    compliance_bundle = authenticated_client_factory(
        identity=identity_for(compliance.external_auth_id, compliance.email),
        database_url=migrated_database_url,
    )

    for bundle in (support_bundle, compliance_bundle):
        assert (
            bundle.client.get(
                "/api/v1/platform/users", params={"status": "active", "q": "needle"}
            ).status_code
            == 403
        )
        assert (
            bundle.client.get(
                "/api/v1/platform/organisations",
                params={"status": "active", "q": "needle"},
            ).status_code
            == 403
        )
        assert (
            bundle.client.get(
                "/api/v1/platform/staff",
                params={"status": "active", "role": "support_agent"},
            ).status_code
            == 403
        )
