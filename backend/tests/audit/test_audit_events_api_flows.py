from __future__ import annotations

import json

from sqlalchemy import select

from app.audit.models.audit_event import AuditEvent
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for
from tests.helpers.outbox import process_all_claimed_outbox_events


class InMemoryInviteTokenSink:
    def __init__(self) -> None:
        self._tokens_by_email: dict[str, list[str]] = {}

    async def deliver(self, *, invite, raw_token: str) -> None:
        self._tokens_by_email.setdefault(invite.email.lower(), []).append(raw_token)

    def token_for_email(self, email: str) -> str:
        return self.tokens_for_email(email)[-1]

    def tokens_for_email(self, email: str) -> list[str]:
        return list(self._tokens_by_email[email.lower()])


def _override_token_sink(monkeypatch) -> InMemoryInviteTokenSink:
    sink = InMemoryInviteTokenSink()
    monkeypatch.setattr("app.outbox.workers.get_invite_token_sink", lambda: sink)
    return sink


def _drain_outbox(migrated_session_factory, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory",
        lambda: migrated_session_factory,
    )
    run_async(process_all_claimed_outbox_events(migrated_session_factory))


def assert_metadata_has_no_sensitive_invite_fields(metadata: dict[str, object]) -> None:
    serialized = json.dumps(metadata).lower()
    assert "token" not in serialized
    assert "token_hash" not in serialized
    assert "email" not in serialized
    assert "authorization" not in serialized
    assert "cookie" not in serialized


def _events(migrated_session_factory):
    async def _query() -> list[AuditEvent]:
        async with migrated_session_factory() as session:
            result = await session.execute(select(AuditEvent))
            return list(result.scalars().all())

    return run_async(_query())


def _event_by_action(migrated_session_factory, action: str) -> AuditEvent:
    events = _events(migrated_session_factory)
    event = next((item for item in events if item.action == action), None)
    assert event is not None
    return event


def test_organisation_update_writes_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-update", "audit-owner-update@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org Update", "slug": "audit-org-update"},
        )
        organisation_id = create.json()["id"]
        response = client.patch(
            f"/api/v1/organisations/{organisation_id}",
            json={"slug": "audit-org-update-2"},
        )
        assert response.status_code == 200

    event = _event_by_action(migrated_session_factory, "organisation_updated")
    assert event.target_type == "organisation"


def test_invite_resend_writes_audit_event_without_sensitive_metadata(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-resend", "audit-owner-resend@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org Resend", "slug": "audit-org-resend"},
        )
        organisation_id = create.json()["id"]
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-resend@example.com", "role": "member"},
        )
        invite_id = invite.json()["id"]
        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend"
        )
        assert response.status_code == 200

    _drain_outbox(migrated_session_factory, monkeypatch)
    assert owner_sink.token_for_email("audit-member-resend@example.com")
    event = _event_by_action(migrated_session_factory, "invite_resent")
    assert event.metadata_json is not None
    assert event.reason is None
    assert_metadata_has_no_sensitive_invite_fields(event.metadata_json)


def test_invite_create_writes_audit_event_without_sensitive_metadata(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-create", "audit-owner-create@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org Create", "slug": "audit-org-create"},
        )
        organisation_id = create.json()["id"]
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-create@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    event = _event_by_action(migrated_session_factory, "invite_created")
    assert event.metadata_json == {
        "organisation_id": str(organisation_id),
        "invite_role": "member",
    }
    assert_metadata_has_no_sensitive_invite_fields(event.metadata_json)


def test_invite_revoke_writes_audit_event_without_sensitive_metadata(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-revoke", "audit-owner-revoke@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org Revoke", "slug": "audit-org-revoke"},
        )
        organisation_id = create.json()["id"]
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-revoke@example.com", "role": "member"},
        )
        invite_id = invite.json()["id"]
        response = client.request(
            "DELETE",
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}",
            json={"reason": "  stale request  "},
        )
        assert response.status_code == 204

    event = _event_by_action(migrated_session_factory, "invite_revoked")
    assert event.metadata_json is not None
    assert_metadata_has_no_sensitive_invite_fields(event.metadata_json)


def test_membership_role_change_writes_audit_event(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for("kc-audit-owner-role", "audit-owner-role@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)
    member_bundle = authenticated_client_factory(
        identity=identity_for("kc-audit-member-role", "audit-member-role@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org Role", "slug": "audit-org-role"},
        )
        organisation_id = create.json()["id"]
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-role@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    raw_token = owner_sink.token_for_email("audit-member-role@example.com")
    with member_bundle.client as client:
        accept = client.post("/api/v1/invites/accept", json={"token": raw_token})
        assert accept.status_code == 200
        membership_id = accept.json()["membership_id"]

    with owner_bundle.client as client:
        response = client.patch(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
            json={"role": "admin"},
        )
        assert response.status_code == 200

    event = _event_by_action(migrated_session_factory, "membership_role_changed")
    assert event.metadata_json["old_role"] == "member"
    assert event.metadata_json["new_role"] == "admin"


def test_membership_remove_writes_audit_event(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-remove-member", "audit-owner-remove-member@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)
    member_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-member-remove-member", "audit-member-remove-member@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org Remove", "slug": "audit-org-remove-member"},
        )
        organisation_id = create.json()["id"]
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-remove-member@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    raw_token = owner_sink.token_for_email("audit-member-remove-member@example.com")
    with member_bundle.client as client:
        accept = client.post("/api/v1/invites/accept", json={"token": raw_token})
        assert accept.status_code == 200
        membership_id = accept.json()["membership_id"]

    with owner_bundle.client as client:
        response = client.request(
            "DELETE",
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}",
            json={"reason": "  access revoked  "},
        )
        assert response.status_code == 204

    event = _event_by_action(migrated_session_factory, "membership_removed")
    assert event.metadata_json["previous_role"] == "member"
    assert event.reason == "access revoked"


def test_organisation_delete_writes_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-delete", "audit-owner-delete@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Audit Org Delete", "slug": "audit-org-delete"},
        )
        organisation_id = create.json()["id"]
        response = client.request(
            "DELETE",
            f"/api/v1/organisations/{organisation_id}",
            json={"reason": "  tenant closure  "},
        )
        assert response.status_code == 204

    event = _event_by_action(migrated_session_factory, "organisation_deleted")
    assert event.target_type == "organisation"
    assert event.reason == "tenant closure"
    assert event.metadata_json["soft_delete"] is True


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


def test_noop_organisation_update_does_not_write_audit_event(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-noop-org", "audit-owner-noop-org@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Noop Org", "slug": "noop-org"},
        )
        organisation_id = create.json()["id"]
        response = client.patch(
            f"/api/v1/organisations/{organisation_id}",
            json={"name": "  Noop Org  ", "slug": "NOOP-ORG"},
        )
        assert response.status_code == 200

    events = _events(migrated_session_factory)
    assert not [event for event in events if event.action == "organisation_updated"]


def test_noop_membership_role_change_returns_409_without_audit_event(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-owner-noop-role", "audit-owner-noop-role@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)
    member_bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-audit-member-noop-role", "audit-member-noop-role@example.com"
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations",
            json={"name": "Noop Role Org", "slug": "noop-role-org"},
        )
        organisation_id = create.json()["id"]
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "audit-member-noop-role@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    raw_token = owner_sink.token_for_email("audit-member-noop-role@example.com")
    with member_bundle.client as client:
        accept = client.post("/api/v1/invites/accept", json={"token": raw_token})
        membership_id = accept.json()["membership_id"]

    with owner_bundle.client as client:
        response = client.patch(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
            json={"role": "member"},
        )
        assert response.status_code == 409

    events = _events(migrated_session_factory)
    assert not [event for event in events if event.action == "membership_role_changed"]
