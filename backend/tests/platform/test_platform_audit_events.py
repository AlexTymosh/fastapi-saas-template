from uuid import uuid4

from app.audit.models.audit_event import AuditEvent
from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

SENSITIVE_AUDIT_FIELDS = {
    "actor_user_id",
    "reason",
    "metadata_json",
    "ip_address",
    "user_agent",
}
LIMITED_AUDIT_FIELDS = {
    "id",
    "category",
    "action",
    "target_type",
    "target_id",
    "has_actor",
    "has_reason",
    "has_metadata",
    "created_at",
}


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


def _seed_audit_event(
    session_factory,
    *,
    actor_user_id,
    category: str = "platform",
    action: str = "user_suspended",
    target_type: str = "user",
    target_id=None,
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                event = AuditEvent(
                    actor_user_id=actor_user_id,
                    category=category,
                    action=action,
                    target_type=target_type,
                    target_id=target_id or uuid4(),
                    reason="Investigated user-provided support details",
                    metadata_json={"ticket_id": "SUP-123", "scope": "triage"},
                    ip_address="203.0.113.24",
                    user_agent="Mozilla/5.0 security regression test",
                )
                session.add(event)
                await session.flush()
                await session.refresh(event)
                return event

    return run_async(_run())


def test_platform_admin_and_compliance_can_list_audit_events(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-pa",
        email="pa@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    _seed_audit_event(migrated_session_factory, actor_user_id=admin.id)
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

        audit_event = payload["data"][0]
        for field in SENSITIVE_AUDIT_FIELDS:
            assert field in audit_event
        assert audit_event["actor_user_id"] == str(admin.id)
        assert audit_event["reason"] == "Investigated user-provided support details"
        assert audit_event["metadata_json"] == {
            "ticket_id": "SUP-123",
            "scope": "triage",
        }
        assert audit_event["ip_address"] == "203.0.113.24"
        assert audit_event["user_agent"] == "Mozilla/5.0 security regression test"


def test_support_agent_cannot_list_full_audit_events_but_can_list_limited_view(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    support = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-sa",
        email="sa@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    _seed_audit_event(migrated_session_factory, actor_user_id=support.id)
    bundle = authenticated_client_factory(
        identity=identity_for("kc-sa", "sa@example.com"),
        database_url=migrated_database_url,
    )

    assert bundle.client.get("/api/v1/platform/audit-events").status_code == 403

    response = bundle.client.get("/api/v1/platform/audit-events/limited")
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    audit_event = payload["data"][0]
    assert set(audit_event) == LIMITED_AUDIT_FIELDS
    assert SENSITIVE_AUDIT_FIELDS.isdisjoint(audit_event)
    assert audit_event["has_actor"] is True
    assert audit_event["has_reason"] is True
    assert audit_event["has_metadata"] is True
    assert audit_event["category"] == "platform"
    assert audit_event["action"] == "user_suspended"
    assert audit_event["target_type"] == "user"


def test_regular_user_cannot_list_full_or_limited_audit_events(
    authenticated_client_factory, migrated_database_url
):
    regular = authenticated_client_factory(
        identity=identity_for("kc-regular", "regular@example.com"),
        database_url=migrated_database_url,
    )
    assert regular.client.get("/api/v1/platform/audit-events").status_code == 403
    assert (
        regular.client.get("/api/v1/platform/audit-events/limited").status_code == 403
    )


def test_audit_event_filters_apply_to_full_and_limited_views(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
):
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-pa-filter",
        email="pa-filter@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    target_id = uuid4()
    _seed_audit_event(
        migrated_session_factory,
        actor_user_id=admin.id,
        category="platform",
        action="user_suspended",
        target_type="user",
        target_id=target_id,
    )
    _seed_audit_event(
        migrated_session_factory,
        actor_user_id=admin.id,
        category="tenant",
        action="invite_created",
        target_type="invite",
    )
    bundle = authenticated_client_factory(
        identity=identity_for("kc-pa-filter", "pa-filter@example.com"),
        database_url=migrated_database_url,
    )

    query = (
        "category=platform&action=user_suspended&target_type=user"
        f"&target_id={target_id}"
    )
    for path in (
        "/api/v1/platform/audit-events",
        "/api/v1/platform/audit-events/limited",
    ):
        response = bundle.client.get(f"{path}?{query}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["meta"]["total"] == 1
        assert payload["data"][0]["target_id"] == str(target_id)
        assert payload["data"][0]["category"] == "platform"
        assert payload["data"][0]["action"] == "user_suspended"
        assert payload["data"][0]["target_type"] == "user"


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
    for path in (
        "/api/v1/platform/audit-events",
        "/api/v1/platform/audit-events/limited",
    ):
        assert bundle.client.get(f"{path}?limit=101").status_code == 422
        assert bundle.client.get(f"{path}?offset=-1").status_code == 422
