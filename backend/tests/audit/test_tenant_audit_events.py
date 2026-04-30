from __future__ import annotations

from uuid import UUID

from sqlalchemy import inspect, select

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditEvent
from app.audit.services.audit_events import AuditEventService
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
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


def test_audit_table_exists_and_service_can_insert(migrated_session_factory) -> None:
    async def _assertion() -> None:
        async with migrated_session_factory() as session:
            tables = await session.run_sync(
                lambda sync_s: inspect(sync_s.bind).get_table_names()
            )
            assert "audit_events" in tables

            user = User(
                external_auth_id="kc-audit-smoke", email="audit-smoke@example.com"
            )
            session.add(user)
            await session.flush()

            event = await AuditEventService(session).record_event(
                actor_user_id=user.id,
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type="organisation",
                target_id=None,
                metadata_json={"changed_fields": ["slug"]},
            )
            await session.commit()
            assert event.actor_user_id == user.id
            assert event.metadata_json == {"changed_fields": ["slug"]}

    run_async(_assertion())


def test_organisation_update_and_delete_emit_audit(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = _identity_for("kc-audit-org-owner", "audit-org-owner@example.com")
    _provision(authenticated_client_factory, migrated_database_url, owner)
    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations", json={"name": "Audit Org", "slug": "audit-org"}
        )
        organisation_id = UUID(create.json()["id"])
        update = client.patch(
            f"/api/v1/organisations/{organisation_id}", json={"slug": "audit-org-upd"}
        )
        assert update.status_code == 200
        delete = client.delete(f"/api/v1/organisations/{organisation_id}")
        assert delete.status_code == 204

    async def _assertion() -> None:
        async with migrated_session_factory() as session:
            events = list(
                (
                    await session.execute(
                        select(AuditEvent).where(
                            AuditEvent.target_id == organisation_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            actions = {event.action for event in events}
            assert AuditAction.ORGANISATION_UPDATED in actions
            assert AuditAction.ORGANISATION_DELETED in actions

    run_async(_assertion())


def test_membership_and_invite_emit_audit_and_forbidden_does_not_emit(
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
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    outsider_bundle = authenticated_client_factory(
        identity=outsider, database_url=migrated_database_url, redis_url=None
    )

    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations", json={"name": "Audit Team", "slug": "audit-team"}
        )
        organisation_id = create.json()["id"]

    async def _seed_membership() -> UUID:
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

    membership_id = run_async(_seed_membership())

    with owner_bundle.client as client:
        role_change = client.patch(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
            json={"role": "admin"},
        )
        assert role_change.status_code == 200
        remove = client.delete(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}"
        )
        assert remove.status_code == 204

        invite = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "new-user@example.com", "role": "member"},
        )
        invite_id = invite.json()["id"]
        resend = client.post(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend"
        )
        assert resend.status_code == 200
        revoke = client.delete(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}"
        )
        assert revoke.status_code == 204

    with outsider_bundle.client as client:
        forbidden = client.delete(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}"
        )
        assert forbidden.status_code == 403

    async def _assertion() -> None:
        async with migrated_session_factory() as session:
            events = list((await session.execute(select(AuditEvent))).scalars().all())
            assert any(e.action == AuditAction.MEMBERSHIP_ROLE_CHANGED for e in events)
            assert any(e.action == AuditAction.MEMBERSHIP_REMOVED for e in events)
            revoke_event = next(
                e for e in events if e.action == AuditAction.INVITE_REVOKED
            )
            assert revoke_event.category == AuditCategory.TENANT
            assert "token" not in (revoke_event.metadata_json or {})
            assert "token_hash" not in (revoke_event.metadata_json or {})
            resent_event = next(
                e for e in events if e.action == AuditAction.INVITE_RESENT
            )
            assert "token" not in (resent_event.metadata_json or {})
            assert "token_hash" not in (resent_event.metadata_json or {})

    run_async(_assertion())
