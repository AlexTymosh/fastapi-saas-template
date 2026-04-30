from __future__ import annotations

import json

from sqlalchemy import select

from app.audit.models.audit_event import AuditEvent
from app.invites.services.delivery import get_invite_token_sink
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for


class InMemoryInviteTokenSink:
    def __init__(self) -> None:
        self._tokens_by_invite_id: dict[str, str] = {}

    async def deliver(self, *, invite, raw_token: str) -> None:
        self._tokens_by_invite_id[str(invite.id)] = raw_token


def _override_token_sink(test_client) -> None:
    sink = InMemoryInviteTokenSink()
    test_client.app.dependency_overrides[get_invite_token_sink] = lambda: sink


def _event_by_action(events: list[AuditEvent], action: str) -> AuditEvent:
    return next(event for event in events if event.action == action)


def assert_metadata_has_no_sensitive_invite_fields(metadata: dict[str, object]) -> None:
    serialised = json.dumps(metadata).lower()
    assert "token" not in serialised
    assert "token_hash" not in serialised
    assert "email" not in serialised


def test_sensitive_actions_write_audit_events(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = identity_for("kc-audit-owner", "audit-owner@example.com")
    member = identity_for("kc-audit-member", "audit-member@example.com")

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    member_bundle = authenticated_client_factory(
        identity=member, database_url=migrated_database_url, redis_url=None
    )

    _override_token_sink(owner_bundle.client)
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

        invite_response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201
        invite_id = invite_response.json()["id"]

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        owner_user_id = me.json()["id"]

        users = client.get(f"/api/v1/organisations/{organisation_id}/users")
        assert users.status_code == 200
        member_entry = next(
            item for item in users.json()["data"] if item["id"] != owner_user_id
        )
        membership_id = member_entry["membership"]["id"]

        change_role = client.patch(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
            json={"role": "admin"},
        )
        assert change_role.status_code == 200

        revoke = client.delete(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}"
        )
        assert revoke.status_code == 204

        invite_response_2 = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member@example.com", "role": "member"},
        )
        assert invite_response_2.status_code == 201
        invite_id_2 = invite_response_2.json()["id"]

        resend = client.post(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id_2}/resend"
        )
        assert resend.status_code == 200

        remove = client.delete(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}"
        )
        assert remove.status_code == 204

        delete_org = client.delete(f"/api/v1/organisations/{organisation_id}")
        assert delete_org.status_code == 204

    async def _query_events() -> list[AuditEvent]:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(AuditEvent).order_by(AuditEvent.created_at.asc())
            )
            return list(result.scalars().all())

    events = run_async(_query_events())

    updated = _event_by_action(events, "organisation_updated")
    assert updated.category == "tenant"
    assert updated.target_type == "organisation"
    assert updated.metadata_json is not None
    assert "changed_fields" in updated.metadata_json

    deleted = _event_by_action(events, "organisation_deleted")
    assert deleted.target_id is not None
    assert deleted.target_type == "organisation"
    assert deleted.metadata_json is not None
    assert deleted.metadata_json["previous_slug"] == "audit-org-2"
    assert deleted.metadata_json["deleted_slug"] == "audit-org-2--deleted"
    assert deleted.metadata_json["soft_delete"] is True

    role_changed = _event_by_action(events, "membership_role_changed")
    assert role_changed.target_type == "membership"
    assert role_changed.metadata_json is not None
    assert role_changed.metadata_json["organisation_id"] == organisation_id
    assert role_changed.metadata_json["old_role"] == "member"
    assert role_changed.metadata_json["new_role"] == "admin"

    removed = _event_by_action(events, "membership_removed")
    assert removed.target_type == "membership"
    assert removed.metadata_json is not None
    assert removed.metadata_json["organisation_id"] == organisation_id
    assert removed.metadata_json["previous_role"] == "admin"
    assert removed.metadata_json["removed_user_id"]

    invite_revoked = _event_by_action(events, "invite_revoked")
    assert invite_revoked.target_type == "invite"
    assert invite_revoked.metadata_json is not None
    assert invite_revoked.metadata_json["organisation_id"] == organisation_id
    assert invite_revoked.metadata_json["invite_role"] == "member"
    assert invite_revoked.metadata_json["invite_status_before"] == "pending"
    assert_metadata_has_no_sensitive_invite_fields(invite_revoked.metadata_json)

    invite_resent = _event_by_action(events, "invite_resent")
    assert invite_resent.target_type == "invite"
    assert invite_resent.metadata_json is not None
    assert invite_resent.metadata_json["organisation_id"] == organisation_id
    assert invite_resent.metadata_json["invite_role"] == "member"
    assert_metadata_has_no_sensitive_invite_fields(invite_resent.metadata_json)


def test_failed_permission_does_not_write_success_audit_event(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
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
            json={"email": "audit-stranger@example.com", "role": "member"},
        )
        invite_id = invite_response.json()["id"]

    with stranger_bundle.client as client:
        response = client.patch(
            f"/api/v1/organisations/{organisation_id}",
            json={"slug": "forbidden-update"},
        )
        assert response.status_code == 403

        revoke_response = client.delete(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}"
        )
        assert revoke_response.status_code == 403

    async def _count() -> tuple[int, int]:
        async with migrated_session_factory() as session:
            org_result = await session.execute(
                select(AuditEvent).where(AuditEvent.action == "organisation_updated")
            )
            invite_result = await session.execute(
                select(AuditEvent).where(AuditEvent.action == "invite_revoked")
            )
            return len(list(org_result.scalars().all())), len(
                list(invite_result.scalars().all())
            )

    organisation_updates, invite_revokes = run_async(_count())
    assert organisation_updates == 0
    assert invite_revokes == 0
