from __future__ import annotations

from uuid import UUID

from sqlalchemy import inspect, select

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditEvent
from app.audit.services.audit_events import AuditEventService
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.api.test_invites import _override_token_sink
from tests.api.test_users_organisations import _identity_for
from tests.helpers.asyncio_runner import run_async


def test_audit_table_exists_and_repository_persists(migrated_session_factory) -> None:
    async def _assert_audit() -> None:
        async with migrated_session_factory() as session:
            table_names = inspect(session.bind.sync_engine).get_table_names()
            assert "audit_events" in table_names
            event = await AuditEventService(session).record_event(
                actor_user_id=None,
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type="organisation",
                target_id=None,
                metadata_json={"changed_fields": ["slug"]},
            )
            await session.commit()
            assert event.id is not None
            persisted = (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.id == event.id)
                )
            ).scalar_one()
            assert persisted.metadata_json == {"changed_fields": ["slug"]}

    run_async(_assert_audit())


def test_sensitive_tenant_actions_write_audit_events(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner = _identity_for("kc-audit-owner", "audit-owner@example.com")
    member = _identity_for("kc-audit-member", "audit-member@example.com")

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    member_bundle = authenticated_client_factory(
        identity=member, database_url=migrated_database_url, redis_url=None
    )
    _override_token_sink(owner_bundle.client)

    with member_bundle.client as client:
        assert client.get("/api/v1/users/me").status_code == 200

    with owner_bundle.client as client:
        assert client.get("/api/v1/users/me").status_code == 200
        create_org = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org"}
        )
        assert create_org.status_code == 201
        organisation_id = create_org.json()["id"]

    async def _seed_membership() -> UUID:
        async with migrated_session_factory() as session:
            member_user = (
                await session.execute(
                    select(User).where(User.external_auth_id == "kc-audit-member")
                )
            ).scalar_one()
            membership = Membership(
                user_id=member_user.id,
                organisation_id=UUID(organisation_id),
                role=MembershipRole.MEMBER,
            )
            session.add(membership)
            await session.commit()
            await session.refresh(membership)
            return membership.id

    membership_id = run_async(_seed_membership())

    with owner_bundle.client as client:
        assert (
            client.patch(
                f"/api/v1/organisations/{organisation_id}",
                json={"slug": "audit-org-new"},
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
        assert (
            client.delete(
                f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}"
            ).status_code
            == 204
        )
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invited@example.com", "role": "member"},
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
            client.delete(f"/api/v1/organisations/{organisation_id}").status_code == 204
        )

    with member_bundle.client as client:
        forbidden = client.patch(
            f"/api/v1/organisations/{organisation_id}", json={"name": "Nope"}
        )
        assert forbidden.status_code == 403

    async def _assert_events() -> None:
        async with migrated_session_factory() as session:
            events = list((await session.execute(select(AuditEvent))).scalars().all())
            by_action = {event.action: event for event in events}
            assert AuditAction.ORGANISATION_UPDATED in by_action
            assert AuditAction.ORGANISATION_DELETED in by_action
            assert AuditAction.MEMBERSHIP_ROLE_CHANGED in by_action
            assert AuditAction.MEMBERSHIP_REMOVED in by_action
            assert AuditAction.INVITE_REVOKED in by_action
            assert AuditAction.INVITE_RESENT in by_action

            updated = by_action[AuditAction.ORGANISATION_UPDATED]
            assert updated.category == AuditCategory.TENANT
            assert updated.target_type == "organisation"
            assert updated.target_id == UUID(organisation_id)
            assert "slug" in updated.metadata_json["changed_fields"]

            role_changed = by_action[AuditAction.MEMBERSHIP_ROLE_CHANGED]
            assert role_changed.metadata_json["old_role"] == "member"
            assert role_changed.metadata_json["new_role"] == "admin"

            removed = by_action[AuditAction.MEMBERSHIP_REMOVED]
            assert removed.metadata_json["removed_user_id"]
            assert removed.metadata_json["previous_role"]

            revoked = by_action[AuditAction.INVITE_REVOKED]
            resent = by_action[AuditAction.INVITE_RESENT]
            for payload in (revoked.metadata_json, resent.metadata_json):
                assert "token" not in payload
                assert "token_hash" not in payload

            failed_update_count = sum(
                1
                for event in events
                if event.action == AuditAction.ORGANISATION_UPDATED
            )
            assert failed_update_count == 1

    run_async(_assert_events())
