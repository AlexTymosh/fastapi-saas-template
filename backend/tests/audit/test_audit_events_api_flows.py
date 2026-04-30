from __future__ import annotations

from sqlalchemy import select

from app.audit.models.audit_event import AuditEvent
from tests.api.test_invites import _identity_for
from tests.helpers.asyncio_runner import run_async


def test_sensitive_actions_write_audit_events(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = _identity_for("kc-audit-owner", "audit-owner@example.com")
    member = _identity_for("kc-audit-member", "audit-member@example.com")

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    member_bundle = authenticated_client_factory(
        identity=member, database_url=migrated_database_url, redis_url=None
    )

    with member_bundle.client as client:
        client.get("/api/v1/users/me")

    with owner_bundle.client as client:
        create_org = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org"}
        )
        assert create_org.status_code == 201
        organisation_id = create_org.json()["id"]

        update_org = client.patch(
            f"/api/v1/organisations/{organisation_id}",
            json={"slug": "audit-org-2"},
        )
        assert update_org.status_code == 200

    async def _query_events() -> list[AuditEvent]:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(AuditEvent).order_by(AuditEvent.created_at.asc())
            )
            return list(result.scalars().all())

    events = run_async(_query_events())
    updated = [event for event in events if event.action == "organisation_updated"]
    assert len(updated) == 1
    assert updated[0].category == "tenant"
    assert updated[0].target_type == "organisation"
    assert updated[0].metadata_json is not None
    assert "changed_fields" in updated[0].metadata_json
    assert "old_name" not in updated[0].metadata_json
    assert "new_name" not in updated[0].metadata_json


def test_failed_permission_does_not_write_success_audit_event(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = _identity_for("kc-audit-owner2", "audit-owner2@example.com")
    stranger = _identity_for("kc-audit-stranger", "audit-stranger@example.com")

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    stranger_bundle = authenticated_client_factory(
        identity=stranger, database_url=migrated_database_url, redis_url=None
    )

    with owner_bundle.client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org 2", "slug": "audit-org-22"},
        )
        organisation_id = create_org.json()["id"]

    with stranger_bundle.client as client:
        response = client.patch(
            f"/api/v1/organisations/{organisation_id}",
            json={"slug": "forbidden-update"},
        )
        assert response.status_code == 403

    async def _count() -> int:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(AuditEvent).where(AuditEvent.action == "organisation_updated")
            )
            return len(list(result.scalars().all()))

    assert run_async(_count()) == 0
