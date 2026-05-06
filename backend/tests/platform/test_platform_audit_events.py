from uuid import UUID

import pytest

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.security, pytest.mark.authz, pytest.mark.audit]


def _seed_platform_staff(
    session_factory, *, external_auth_id: str, email: str, role: PlatformRole
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
            return user

    return run_async(_run())


_DEFAULT_METADATA = object()


def _seed_audit_event(
    session_factory,
    *,
    actor_user_id: UUID | None,
    action: AuditAction = AuditAction.USER_SUSPENDED,
    target_type: AuditTargetType = AuditTargetType.USER,
    target_id: UUID | None = None,
    reason: str | None = "Sensitive free-text reason",
    metadata_json: dict[str, object] | None | object = _DEFAULT_METADATA,
    ip_address: str | None = "203.0.113.10",
    user_agent: str | None = "SensitiveBrowser/1.0",
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                return await AuditEventService(session).record_event(
                    audit_context=AuditContext(
                        actor_user_id=actor_user_id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    ),
                    category=AuditCategory.PLATFORM,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    reason=reason,
                    metadata_json=(
                        {"case_id": "SEC-123"}
                        if metadata_json is _DEFAULT_METADATA
                        else metadata_json
                    ),
                )

    return run_async(_run())


def test_platform_admin_and_compliance_can_list_audit_events(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-pa",
        email="pa@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-co",
        email="co@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )

    for external_auth_id, email in (
        ("kc-pa", "pa@example.com"),
        ("kc-co", "co@example.com"),
    ):
        bundle = authenticated_client_factory(
            identity=identity_for(external_auth_id, email),
            database_url=migrated_database_url,
        )
        response = bundle.client.get("/api/v1/platform/audit-events")
        assert response.status_code == 200
        payload = response.json()
        assert "data" in payload
        assert "meta" in payload
        assert "links" in payload
        assert "total" in payload["meta"]
        assert "limit" in payload["meta"]
        assert "offset" in payload["meta"]


def test_full_audit_reader_receives_sensitive_fields(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-full-audit",
        email="full-audit@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    event = _seed_audit_event(
        migrated_session_factory,
        actor_user_id=admin.id,
        target_id=admin.id,
    )

    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.get("/api/v1/platform/audit-events")

    assert response.status_code == 200
    rows = response.json()["data"]
    payload = next(row for row in rows if row["id"] == str(event.id))
    assert payload["actor_user_id"] == str(admin.id)
    assert payload["metadata_json"] == {"case_id": "SEC-123"}
    assert payload["ip_address"] == "203.0.113.10"
    assert payload["user_agent"] == "SensitiveBrowser/1.0"
    assert payload["reason"] == "Sensitive free-text reason"


def test_support_agent_can_list_limited_audit_events_without_sensitive_fields(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    support = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-limited-audit",
        email="limited-audit@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    event = _seed_audit_event(
        migrated_session_factory,
        actor_user_id=support.id,
        target_id=support.id,
    )

    bundle = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.get("/api/v1/platform/audit-events/limited")

    assert response.status_code == 200
    rows = response.json()["data"]
    payload = next(row for row in rows if row["id"] == str(event.id))
    assert payload == {
        "id": str(event.id),
        "category": AuditCategory.PLATFORM.value,
        "action": AuditAction.USER_SUSPENDED.value,
        "target_type": AuditTargetType.USER.value,
        "target_id": str(support.id),
        "has_actor": True,
        "has_metadata": True,
        "has_reason": True,
        "created_at": payload["created_at"],
    }
    assert "actor_user_id" not in payload
    assert "metadata_json" not in payload
    assert "ip_address" not in payload
    assert "user_agent" not in payload
    assert "reason" not in payload


def test_support_agent_and_regular_user_cannot_list_full_audit_events(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-sa",
        email="sa@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    bundle = authenticated_client_factory(
        identity=identity_for("kc-sa", "sa@example.com"),
        database_url=migrated_database_url,
    )
    assert bundle.client.get("/api/v1/platform/audit-events").status_code == 403

    regular = authenticated_client_factory(
        identity=identity_for("kc-regular", "regular@example.com"),
        database_url=migrated_database_url,
    )
    assert regular.client.get("/api/v1/platform/audit-events").status_code == 403
    assert (
        regular.client.get("/api/v1/platform/audit-events/limited").status_code == 403
    )


def test_limited_audit_events_apply_same_filters_as_full_view(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-filter-admin",
        email="filter-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    support = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-filter-support",
        email="filter-support@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    matching_event = _seed_audit_event(
        migrated_session_factory,
        actor_user_id=admin.id,
        action=AuditAction.USER_RESTORED,
        target_type=AuditTargetType.USER,
        target_id=admin.id,
        reason=None,
        metadata_json=None,
        ip_address=None,
        user_agent=None,
    )
    _seed_audit_event(
        migrated_session_factory,
        actor_user_id=admin.id,
        action=AuditAction.ORGANISATION_SUSPENDED,
        target_type=AuditTargetType.ORGANISATION,
    )

    query = (
        f"?category={AuditCategory.PLATFORM.value}"
        f"&action={AuditAction.USER_RESTORED.value}"
        f"&target_type={AuditTargetType.USER.value}"
        f"&target_id={admin.id}"
    )
    admin_bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )
    support_bundle = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
    )

    full_response = admin_bundle.client.get(f"/api/v1/platform/audit-events{query}")
    limited_response = support_bundle.client.get(
        f"/api/v1/platform/audit-events/limited{query}"
    )

    assert full_response.status_code == 200
    assert limited_response.status_code == 200
    assert full_response.json()["meta"]["total"] == 1
    assert limited_response.json()["meta"]["total"] == 1
    assert [row["id"] for row in full_response.json()["data"]] == [
        str(matching_event.id)
    ]
    assert [row["id"] for row in limited_response.json()["data"]] == [
        str(matching_event.id)
    ]
    assert limited_response.json()["data"][0]["has_actor"] is True
    assert limited_response.json()["data"][0]["has_metadata"] is False
    assert limited_response.json()["data"][0]["has_reason"] is False


def test_audit_events_pagination_validation(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-pa-2",
        email="pa2@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    bundle = authenticated_client_factory(
        identity=identity_for("kc-pa-2", "pa2@example.com"),
        database_url=migrated_database_url,
    )
    assert (
        bundle.client.get("/api/v1/platform/audit-events?limit=101").status_code == 422
    )
    assert (
        bundle.client.get("/api/v1/platform/audit-events?offset=-1").status_code == 422
    )
    assert (
        bundle.client.get("/api/v1/platform/audit-events/limited?limit=101").status_code
        == 422
    )
