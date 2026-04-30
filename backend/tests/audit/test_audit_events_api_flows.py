from __future__ import annotations

import json

from sqlalchemy import select

from app.audit.models.audit_event import AuditEvent
from app.invites.services.delivery import get_invite_token_sink
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for
from tests.helpers.invites import InMemoryInviteTokenSink


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


def _latest_event_for_action(migrated_session_factory, action: str) -> AuditEvent:
    events = _events(migrated_session_factory)
    matches = [event for event in events if event.action == action]
    assert matches
    return matches[-1]


def _owner_bundle(authenticated_client_factory, migrated_database_url: str):
    owner = identity_for("kc-audit-owner", "audit-owner@example.com")
    return authenticated_client_factory(
        identity=owner,
        database_url=migrated_database_url,
        redis_url=None,
    )


def test_organisation_update_writes_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = _owner_bundle(authenticated_client_factory, migrated_database_url)

    with owner_bundle.client as client:
        org = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org"}
        )
        organisation_id = org.json()["id"]

        update_org = client.patch(
            f"/api/v1/organisations/{organisation_id}", json={"slug": "audit-org-2"}
        )
        assert update_org.status_code == 200

    event = _latest_event_for_action(migrated_session_factory, "organisation_updated")
    assert event.target_type == "organisation"


def test_organisation_delete_writes_soft_delete_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = _owner_bundle(authenticated_client_factory, migrated_database_url)

    with owner_bundle.client as client:
        org = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org-del"}
        )
        organisation_id = org.json()["id"]

        delete_org = client.delete(f"/api/v1/organisations/{organisation_id}")
        assert delete_org.status_code == 204

    deleted = _latest_event_for_action(migrated_session_factory, "organisation_deleted")
    assert deleted.target_type == "organisation"
    assert deleted.metadata_json["soft_delete"] is True


def test_invite_resend_and_revoke_write_audit_events_without_sensitive_fields(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = _owner_bundle(authenticated_client_factory, migrated_database_url)

    with owner_bundle.client as client:
        org = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org-invite"}
        )
        organisation_id = org.json()["id"]

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

    for action in ("invite_revoked", "invite_resent"):
        metadata = _latest_event_for_action(migrated_session_factory, action).metadata_json
        assert metadata is not None
        assert_metadata_has_no_sensitive_invite_fields(metadata)


def test_membership_role_change_writes_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner = identity_for("kc-audit-owner-role", "audit-owner-role@example.com")
    member = identity_for("kc-audit-member-role", "audit-member-role@example.com")

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    member_bundle = authenticated_client_factory(
        identity=member, database_url=migrated_database_url, redis_url=None
    )

    with member_bundle.client as client:
        assert client.get("/api/v1/users/me").status_code == 200

    with owner_bundle.client as owner_client:
        token_sink = InMemoryInviteTokenSink()
        owner_client.app.dependency_overrides[get_invite_token_sink] = lambda: token_sink

        org = owner_client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org-role"}
        )
        organisation_id = org.json()["id"]

        invite = owner_client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-role@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    with member_bundle.client as member_client:
        accept = member_client.post(
            "/api/v1/invites/accept",
            json={"token": token_sink.token_for_email("audit-member-role@example.com")},
        )
        assert accept.status_code == 200

    with owner_bundle.client as client:
        memberships = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        member_row = next(
            item
            for item in memberships.json()["data"]
            if item["email"] == "audit-member-role@example.com"
        )
        membership_id = member_row["id"]
        change_role = client.patch(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
            json={"role": "admin"},
        )
        assert change_role.status_code == 200

    role_changed = _latest_event_for_action(migrated_session_factory, "membership_role_changed")
    assert role_changed.metadata_json["old_role"] == "member"
    assert role_changed.metadata_json["new_role"] == "admin"


def test_membership_remove_writes_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner = identity_for("kc-audit-owner-remove", "audit-owner-remove@example.com")
    member = identity_for("kc-audit-member-remove", "audit-member-remove@example.com")

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    member_bundle = authenticated_client_factory(
        identity=member, database_url=migrated_database_url, redis_url=None
    )

    with member_bundle.client as client:
        assert client.get("/api/v1/users/me").status_code == 200

    with owner_bundle.client as owner_client:
        token_sink = InMemoryInviteTokenSink()
        owner_client.app.dependency_overrides[get_invite_token_sink] = lambda: token_sink

        org = owner_client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org-remove"}
        )
        organisation_id = org.json()["id"]

        invite = owner_client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-remove@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    with member_bundle.client as member_client:
        accept = member_client.post(
            "/api/v1/invites/accept",
            json={"token": token_sink.token_for_email("audit-member-remove@example.com")},
        )
        assert accept.status_code == 200

    with owner_bundle.client as client:
        memberships = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        member_row = next(
            item
            for item in memberships.json()["data"]
            if item["email"] == "audit-member-remove@example.com"
        )
        membership_id = member_row["id"]

        remove_member = client.delete(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}"
        )
        assert remove_member.status_code == 204

    removed = _latest_event_for_action(migrated_session_factory, "membership_removed")
    assert removed.metadata_json["previous_role"] == "member"


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
