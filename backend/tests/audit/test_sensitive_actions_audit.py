from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditEvent
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.api.test_invites import _identity_for, _override_token_sink
from tests.helpers.asyncio_runner import run_async


def _provision(authenticated_client_factory, database_url: str, identity) -> None:
    bundle = authenticated_client_factory(
        identity=identity, database_url=database_url, redis_url=None
    )
    with bundle.client as client:
        assert client.get("/api/v1/users/me").status_code == 200


def test_sensitive_tenant_actions_write_audit_events(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    owner = _identity_for("kc-audit-owner", "audit-owner@example.com")
    member = _identity_for("kc-audit-member", "audit-member@example.com")
    outsider = _identity_for("kc-audit-outsider", "audit-outsider@example.com")
    _provision(authenticated_client_factory, migrated_database_url, owner)
    _provision(authenticated_client_factory, migrated_database_url, member)

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    _override_token_sink(owner_bundle.client)
    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org"}
        )
        organisation_id = create.json()["id"]

    async def _seed_member() -> UUID:
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

    membership_id = run_async(_seed_member())

    with owner_bundle.client as client:
        patch = client.patch(
            f"/api/v1/organisations/{organisation_id}",
            json={"slug": "audit-org-renamed"},
        )
        assert patch.status_code == 200
        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invited-audit@example.com", "role": "member"},
        )
        invite_id = invite.json()["id"]
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

    outsider_bundle = authenticated_client_factory(
        identity=outsider, database_url=migrated_database_url, redis_url=None
    )
    with outsider_bundle.client as client:
        forbidden = client.patch(
            f"/api/v1/organisations/{organisation_id}", json={"name": "Hacker"}
        )
        assert forbidden.status_code == 403

    async def _assert_audit() -> None:
        async with migrated_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AuditEvent).order_by(AuditEvent.created_at)
                    )
                )
                .scalars()
                .all()
            )
            actions = [row.action for row in rows]
            assert AuditAction.ORGANISATION_UPDATED in actions
            assert AuditAction.ORGANISATION_DELETED in actions
            assert AuditAction.MEMBERSHIP_ROLE_CHANGED in actions
            assert AuditAction.MEMBERSHIP_REMOVED in actions
            assert AuditAction.INVITE_REVOKED in actions
            assert AuditAction.INVITE_RESENT in actions
            for row in rows:
                assert row.category == AuditCategory.TENANT
                if row.action in {
                    AuditAction.INVITE_REVOKED,
                    AuditAction.INVITE_RESENT,
                }:
                    assert row.metadata_json is not None
                    assert "token" not in row.metadata_json
                    assert "token_hash" not in row.metadata_json

    run_async(_assert_audit())
