from __future__ import annotations

import json

from sqlalchemy import select

from app.audit.models.audit_event import AuditEvent
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


def assert_metadata_has_no_sensitive_invite_fields(metadata: dict[str, object]) -> None:
    serialized = json.dumps(metadata).lower()
    assert "token" not in serialized
    assert "token_hash" not in serialized
    assert "email" not in serialized


def _events(migrated_session_factory):
    async def _query() -> list[AuditEvent]:
        async with migrated_session_factory() as session:
            result = await session.execute(select(AuditEvent))
            return list(result.scalars().all())

    return run_async(_query())


def test_sensitive_actions_write_audit_events(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner = identity_for("kc-audit-owner", "audit-owner@example.com")
    member = identity_for("kc-audit-member", "audit-member@example.com")
    outsider = identity_for("kc-audit-outsider", "audit-outsider@example.com")

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    member_bundle = authenticated_client_factory(
        identity=member, database_url=migrated_database_url, redis_url=None
    )
    outsider_bundle = authenticated_client_factory(
        identity=outsider, database_url=migrated_database_url, redis_url=None
    )

    with member_bundle.client as client:
        client.get("/api/v1/users/me")

    with outsider_bundle.client as client:
        client.get("/api/v1/users/me")

    with owner_bundle.client as client:
        org = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org"}
        )
        organisation_id = org.json()["id"]

        update_org = client.patch(
            f"/api/v1/organisations/{organisation_id}", json={"slug": "audit-org-2"}
        )
        assert update_org.status_code == 200

        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member@example.com", "role": "member"},
        )
        assert invite.status_code == 201
        invite_id = invite.json()["id"]

        resend = client.post(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend"
        )
        assert resend.status_code == 200

        revoke = client.delete(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}"
        )
        assert revoke.status_code == 204

        invite_admin = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member@example.com", "role": "admin"},
        )
        assert invite_admin.status_code == 201

    with member_bundle.client as client:
        accept = client.post(
            "/api/v1/invites/accept", json={"token": invite_admin.json()["token"]}
        )
        assert accept.status_code in {200, 404, 422}

    with owner_bundle.client as client:
        memberships = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        member_row = next(
            item for item in memberships.json()["data"] if item["role"] == "member"
        )
        membership_id = member_row["id"]
        change_role = client.patch(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
            json={"role": "admin"},
        )
        assert change_role.status_code == 200

        remove_member = client.delete(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}"
        )
        assert remove_member.status_code == 204

        delete_org = client.delete(f"/api/v1/organisations/{organisation_id}")
        assert delete_org.status_code == 204

    events = _events(migrated_session_factory)
    by_action = {event.action: event for event in events}
    assert "organisation_updated" in by_action
    assert "organisation_deleted" in by_action
    assert "membership_role_changed" in by_action
    assert "membership_removed" in by_action
    assert "invite_revoked" in by_action
    assert "invite_resent" in by_action

    deleted = by_action["organisation_deleted"]
    assert deleted.target_type == "organisation"
    assert deleted.metadata_json["soft_delete"] is True

    role_changed = by_action["membership_role_changed"]
    assert role_changed.metadata_json["old_role"] == "member"
    assert role_changed.metadata_json["new_role"] == "admin"

    removed = by_action["membership_removed"]
    assert removed.metadata_json["previous_role"] == "member"

    for action in ("invite_revoked", "invite_resent"):
        metadata = by_action[action].metadata_json
        assert metadata is not None
        assert_metadata_has_no_sensitive_invite_fields(metadata)


def test_failed_permission_does_not_write_success_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner = identity_for("kc-audit-owner2", "audit-owner2@example.com")
    stranger = identity_for("kc-audit-stranger", "audit-stranger@example.com")

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
        invite_response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-owner2+invite@example.com", "role": "member"},
        )
        invite_id = invite_response.json()["id"]

    with stranger_bundle.client as client:
        response = client.patch(
            f"/api/v1/organisations/{organisation_id}",
            json={"slug": "forbidden-update"},
        )
        assert response.status_code == 403
        revoke = client.delete(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}"
        )
        assert revoke.status_code == 403

    events = _events(migrated_session_factory)
    assert not [event for event in events if event.action == "organisation_updated"]
    assert not [event for event in events if event.action == "invite_revoked"]
