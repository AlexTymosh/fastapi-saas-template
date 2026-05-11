from __future__ import annotations

import pytest

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.repositories.audit_events import AuditEventRepository
from app.organisations.repositories.organisations import OrganisationRepository
from app.platform.models.platform_staff import PlatformStaffRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz]


def _seed_compliance_actor(session_factory):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                actor = await UserService(session).provision_current_user(
                    identity_for("kc-field-compliance", "field-compliance@example.com")
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=actor.id,
                    role=PlatformStaffRole.COMPLIANCE_OFFICER.value,
                )
            return actor

    return run_async(_run())


def _seed_limited_records(session_factory):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for("kc-field-target", "sensitive-target@example.com")
                )
                user.first_name = "Safe"
                user.last_name = "Target"
                user.suspended_reason = "Sensitive user reason"
                org = await OrganisationRepository(session).create(
                    name="Sensitive Organisation",
                    slug="sensitive-organisation",
                )
                org.suspended_reason = "Sensitive organisation reason"
                await AuditEventRepository(session).create(
                    actor_user_id=user.id,
                    category=AuditCategory.PLATFORM,
                    action=AuditAction.USER_SUSPENDED,
                    target_type=AuditTargetType.USER,
                    target_id=user.id,
                    reason="Sensitive audit reason",
                    metadata_json={"safe": "metadata"},
                    ip_address="203.0.113.10",
                    user_agent="Sensitive User Agent",
                )
            return user, org

    return run_async(_run())


def _authenticated_compliance_client(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    actor = _seed_compliance_actor(migrated_session_factory)
    return authenticated_client_factory(
        identity=identity_for(actor.external_auth_id, actor.email),
        database_url=migrated_database_url,
    ).client


def test_limited_user_response_omits_sensitive_and_internal_fields(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    target, _org = _seed_limited_records(migrated_session_factory)
    client = _authenticated_compliance_client(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = client.get("/api/v1/platform/users/limited", params={"q": target.email})

    assert response.status_code == 200
    row = response.json()["data"][0]
    assert set(row) == {"id", "first_name", "last_name", "status", "created_at"}
    assert "external_auth_id" not in row
    assert "email" not in row
    assert target.email not in response.text
    assert "suspended_reason" not in row
    assert "suspended_at" not in row
    assert "email_verified" not in row
    assert "onboarding_completed" not in row


def test_limited_organisation_response_omits_sensitive_and_internal_fields(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    _target, org = _seed_limited_records(migrated_session_factory)
    client = _authenticated_compliance_client(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = client.get(
        "/api/v1/platform/organisations/limited", params={"q": org.slug}
    )

    assert response.status_code == 200
    row = response.json()["data"][0]
    assert set(row) == {"id", "name", "slug", "status", "created_at"}
    assert "suspended_reason" not in row
    assert "deleted_at" not in row
    assert "memberships" not in row
    assert "owner" not in row


def test_limited_audit_response_omits_sensitive_fields(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    _target, _org = _seed_limited_records(migrated_session_factory)
    client = _authenticated_compliance_client(
        authenticated_client_factory, migrated_database_url, migrated_session_factory
    )

    response = client.get("/api/v1/platform/audit-events/limited")

    assert response.status_code == 200
    row = response.json()["data"][0]
    assert "metadata_json" not in row
    assert "ip_address" not in row
    assert "user_agent" not in row
    assert "reason" not in row
    assert "actor_user_id" not in row
