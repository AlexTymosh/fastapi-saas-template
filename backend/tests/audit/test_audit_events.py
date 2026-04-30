from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditEvent
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.api.test_invites import _override_token_sink
from tests.api.test_users_organisations import _identity_for
from tests.helpers.asyncio_runner import run_async


def _provision(authenticated_client_factory, database_url: str, identity) -> None:
    bundle = authenticated_client_factory(
        identity=identity,
        database_url=database_url,
        redis_url=None,
    )
    with bundle.client as client:
        assert client.get("/api/v1/users/me").status_code == 200


def _fetch_audit_events(
    migrated_session_factory, action: AuditAction
) -> list[AuditEvent]:
    async def _inner() -> list[AuditEvent]:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(AuditEvent).where(AuditEvent.action == action)
            )
            return list(result.scalars().all())

    return run_async(_inner())


def test_audit_smoke_insert_and_metadata(migrated_session_factory) -> None:
    async def _inner() -> AuditEvent:
        async with migrated_session_factory() as session:
            event = AuditEvent(
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type="organisation",
                metadata_json={"changed_fields": ["slug"]},
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    event = run_async(_inner())
    assert event.id is not None
    assert event.metadata_json == {"changed_fields": ["slug"]}


def test_sensitive_actions_write_audit_events(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = _identity_for("kc-audit-owner", "audit-owner@example.com")
    member = _identity_for("kc-audit-member", "audit-member@example.com")
    outsider = _identity_for("kc-audit-outsider", "audit-outsider@example.com")
    _provision(authenticated_client_factory, migrated_database_url, owner)
    _provision(authenticated_client_factory, migrated_database_url, member)
    _provision(authenticated_client_factory, migrated_database_url, outsider)

    owner_bundle = authenticated_client_factory(
        identity=owner,
        database_url=migrated_database_url,
        redis_url=None,
    )
    sink = _override_token_sink(owner_bundle.client)

    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org"}
        )
        organisation_id = created.json()["id"]

    async def _insert_member() -> UUID:
        async with migrated_session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.external_auth_id == "kc-audit-member")
                )
            ).scalar_one()
            membership = Membership(
                user_id=user.id,
                organisation_id=UUID(organisation_id),
                role=MembershipRole.MEMBER,
            )
            session.add(membership)
            await session.commit()
            await session.refresh(membership)
            return membership.id

    membership_id = run_async(_insert_member())

    with owner_bundle.client as client:
        assert (
            client.patch(
                f"/api/v1/organisations/{organisation_id}",
                json={"slug": "audit-org-updated"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
                json={"role": "admin"},
            ).status_code
            == 200
        )
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invite-audit@example.com", "role": "member"},
        )
        invite_id = invite.json()["id"]
        assert (
            client.post(
                f"/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend"
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/v1/organisations/{organisation_id}/invites/{invite_id}"
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}"
            ).status_code
            == 204
        )

    with owner_bundle.client as client:
        assert (
            client.delete(f"/api/v1/organisations/{organisation_id}").status_code == 204
        )

    updated_events = _fetch_audit_events(
        migrated_session_factory, AuditAction.ORGANISATION_UPDATED
    )
    assert updated_events[-1].category == AuditCategory.TENANT
    assert updated_events[-1].metadata_json["changed_fields"] == ["slug"]

    deleted_events = _fetch_audit_events(
        migrated_session_factory, AuditAction.ORGANISATION_DELETED
    )
    assert deleted_events[-1].target_type == "organisation"

    role_events = _fetch_audit_events(
        migrated_session_factory, AuditAction.MEMBERSHIP_ROLE_CHANGED
    )
    assert role_events[-1].metadata_json["old_role"] == "member"
    assert role_events[-1].metadata_json["new_role"] == "admin"

    removed_events = _fetch_audit_events(
        migrated_session_factory, AuditAction.MEMBERSHIP_REMOVED
    )
    assert "removed_user_id" in removed_events[-1].metadata_json

    revoked_events = _fetch_audit_events(
        migrated_session_factory, AuditAction.INVITE_REVOKED
    )
    assert "token_hash" not in revoked_events[-1].metadata_json

    resent_events = _fetch_audit_events(
        migrated_session_factory, AuditAction.INVITE_RESENT
    )
    assert "token_hash" not in resent_events[-1].metadata_json

    post_failed_events = _fetch_audit_events(
        migrated_session_factory, AuditAction.ORGANISATION_UPDATED
    )
    assert len(post_failed_events) == len(updated_events)
    assert sink.token_for_email("invite-audit@example.com")
