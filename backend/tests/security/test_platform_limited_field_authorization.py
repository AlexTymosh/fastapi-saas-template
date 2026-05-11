import pytest

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.repositories.audit_events import AuditEventRepository
from app.core.platform.permissions import PlatformRole
from app.organisations.repositories.organisations import OrganisationRepository
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


def _seed_actor(session_factory, *, role: PlatformRole):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(
                        f"kc-field-{role.value}", f"field-{role.value}@example.com"
                    )
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
                await session.flush()
            return user

    return run_async(_run())


def _seed_sensitive_records(session_factory):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                target_user = await UserService(session).provision_current_user(
                    identity_for("kc-sensitive-user", "sensitive.user@example.com")
                )
                target_user.first_name = "Sensitive"
                target_user.last_name = "User"
                target_user.status = UserStatus.SUSPENDED
                target_user.suspended_reason = "private user suspension reason"
                target_user.onboarding_completed = True

                org = await OrganisationRepository(session).create(
                    name="Sensitive Organisation",
                    slug="sensitive-org",
                )
                org.suspended_reason = "private organisation suspension reason"

                await AuditEventRepository(session).create(
                    actor_user_id=target_user.id,
                    category=AuditCategory.PLATFORM,
                    action=AuditAction.USER_SUSPENDED,
                    target_type=AuditTargetType.USER,
                    target_id=target_user.id,
                    reason="private audit reason",
                    metadata_json={"ticket": "SEC-1"},
                    ip_address="203.0.113.10",
                    user_agent="sensitive-agent",
                )
                await session.flush()

    run_async(_run())


def test_limited_user_response_omits_sensitive_and_internal_fields(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_sensitive_records(migrated_session_factory)
    actor = _seed_actor(migrated_session_factory, role=PlatformRole.SUPPORT_AGENT)
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get(
        "/api/v1/platform/users/limited", params={"q": "sensitive"}
    )

    assert response.status_code == 200
    row = response.json()["data"][0]
    assert set(row) == {"id", "first_name", "last_name", "status", "created_at"}
    assert "sensitive.user@example.com" not in response.text
    for forbidden in (
        "email",
        "external_auth_id",
        "suspended_reason",
        "suspended_at",
        "email_verified",
        "onboarding_completed",
    ):
        assert forbidden not in row


def test_limited_organisation_response_omits_sensitive_and_internal_fields(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_sensitive_records(migrated_session_factory)
    actor = _seed_actor(migrated_session_factory, role=PlatformRole.SUPPORT_AGENT)
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get(
        "/api/v1/platform/organisations/limited", params={"q": "sensitive"}
    )

    assert response.status_code == 200
    row = response.json()["data"][0]
    assert set(row) == {"id", "name", "slug", "status", "created_at"}
    for forbidden in (
        "suspended_reason",
        "suspended_at",
        "deleted_at",
        "owner",
        "memberships",
        "membership",
    ):
        assert forbidden not in row


def test_limited_audit_response_omits_sensitive_audit_fields(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    _seed_sensitive_records(migrated_session_factory)
    actor = _seed_actor(migrated_session_factory, role=PlatformRole.SUPPORT_AGENT)
    bundle = authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.get("/api/v1/platform/audit-events/limited")

    assert response.status_code == 200
    row = response.json()["data"][0]
    for forbidden in (
        "metadata_json",
        "ip_address",
        "user_agent",
        "reason",
        "actor_user_id",
    ):
        assert forbidden not in row
    assert row["has_actor"] is True
    assert row["has_metadata"] is True
    assert row["has_reason"] is True
