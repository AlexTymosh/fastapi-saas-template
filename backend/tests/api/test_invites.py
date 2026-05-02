from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.audit.models.audit_event import AuditEvent
from app.core.auth import AuthenticatedPrincipal
from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async
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


class FailingInviteTokenSink:
    async def deliver(self, *, invite, raw_token: str) -> None:
        raise RuntimeError("delivery unavailable")


def _identity_for(
    external_auth_id: str,
    email: str,
    roles: list[str] | None = None,
    *,
    email_verified: bool = True,
) -> AuthenticatedPrincipal:
    claims: dict[str, object] = {
        "sub": external_auth_id,
        "email": email,
        "email_verified": email_verified,
    }
    if roles is not None:
        claims["roles"] = roles
    return AuthenticatedPrincipal.from_unverified_jwt_claims(claims)


def _override_token_sink(monkeypatch) -> InMemoryInviteTokenSink:
    sink = InMemoryInviteTokenSink()
    monkeypatch.setattr("app.outbox.workers.get_invite_token_sink", lambda: sink)
    return sink


def _override_failing_token_sink(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_invite_token_sink",
        lambda: FailingInviteTokenSink(),
    )


def _drain_outbox(migrated_session_factory, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory",
        lambda: migrated_session_factory,
    )
    run_async(process_all_claimed_outbox_events(migrated_session_factory))


def test_invite_accept_rejects_when_user_already_has_active_membership(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    sink = _override_token_sink(monkeypatch)

    source_owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-source-owner", "source-owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    source_owner_client = source_owner_client_bundle.client

    with source_owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Source", "slug": "org-source"},
        )
        assert create_org.status_code == 201
        source_org_id = create_org.json()["id"]

        seed_invite = client.post(
            f"/api/v1/organisations/{source_org_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert seed_invite.status_code == 201

    with owner_client as client:
        create_target_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org A", "slug": "orga"},
        )
        assert create_target_org.status_code == 201
        target_org_id = create_target_org.json()["id"]

        transfer_invite = client.post(
            f"/api/v1/organisations/{target_org_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert transfer_invite.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    tokens = sink.tokens_for_email("invitee@example.com")
    assert len(tokens) == 2
    source_token = tokens[0]
    transfer_token = tokens[1]

    invitee_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee", "invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    invitee_client = invitee_client_bundle.client

    with invitee_client as client:
        accepted_source = client.post(
            "/api/v1/invites/accept",
            json={"token": source_token},
        )
        assert accepted_source.status_code == 200

        accepted = client.post(
            "/api/v1/invites/accept",
            json={"token": transfer_token},
        )
        assert accepted.status_code == 409
        assert accepted.headers["content-type"].startswith("application/problem+json")
        assert accepted.json()["error_code"] == "conflict"

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        assert me.json()["membership"]["organisation_id"] == source_org_id

    async def _assert_membership_not_transferred() -> None:
        async with migrated_session_factory() as session:
            user_result = await session.execute(
                select(User).where(User.external_auth_id == "kc-invitee")
            )
            invitee = user_result.scalar_one()

            memberships_result = await session.execute(
                select(Membership).where(Membership.user_id == invitee.id)
            )
            memberships = list(memberships_result.scalars().all())
            assert len(memberships) == 1

            source_membership = next(
                membership
                for membership in memberships
                if str(membership.organisation_id) == source_org_id
            )

            assert source_membership.is_active is True
            invite_result = await session.execute(
                select(Invite).where(
                    Invite.organisation_id == UUID(target_org_id),
                    Invite.email == "invitee@example.com",
                )
            )
            invite = invite_result.scalar_one()
            assert invite.status == InviteStatus.PENDING

    run_async(_assert_membership_not_transferred())


def test_accept_invite_returns_conflict_when_user_already_has_active_membership(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_a_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-a", "owner-a@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_b_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-b", "owner-b@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    sink = _override_token_sink(monkeypatch)

    with owner_a_bundle.client as client:
        org_a = client.post(
            "/api/v1/organisations",
            json={"name": "Org A Source", "slug": "org-a-source"},
        )
        source_org_id = org_a.json()["id"]
        invited = client.post(
            f"/api/v1/organisations/{source_org_id}/invites",
            json={"email": "active-user@example.com", "role": "member"},
        )
        assert invited.status_code == 201

    with owner_b_bundle.client as client:
        org_b = client.post(
            "/api/v1/organisations",
            json={"name": "Org B Target", "slug": "org-b-target"},
        )
        target_org_id = org_b.json()["id"]
        invited = client.post(
            f"/api/v1/organisations/{target_org_id}/invites",
            json={"email": "active-user@example.com", "role": "member"},
        )
        assert invited.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    tokens = sink.tokens_for_email("active-user@example.com")
    assert len(tokens) == 2
    first_token = tokens[0]
    second_token = tokens[1]
    invitee_bundle = authenticated_client_factory(
        identity=_identity_for("kc-active-user", "active-user@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with invitee_bundle.client as client:
        first_accept = client.post(
            "/api/v1/invites/accept",
            json={"token": first_token},
        )
        assert first_accept.status_code == 200
        second_accept = client.post(
            "/api/v1/invites/accept",
            json={"token": second_token},
        )
        assert second_accept.status_code == 409

    async def _assert_single_active_membership() -> None:
        async with migrated_session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.external_auth_id == "kc-active-user")
                )
            ).scalar_one()
            memberships = (
                (
                    await session.execute(
                        select(Membership).where(Membership.user_id == user.id)
                    )
                )
                .scalars()
                .all()
            )
            active = [membership for membership in memberships if membership.is_active]
            assert len(active) == 1

    run_async(_assert_single_active_membership())


def test_invite_accept_token_cannot_be_double_used_under_parallel_requests(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-double", "owner-double@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    sink = _override_token_sink(monkeypatch)

    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Org Parallel", "slug": "org-parallel"},
        )
        assert created.status_code == 201
        org_id = created.json()["id"]
        invite = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "parallel@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    token = sink.token_for_email("parallel@example.com")

    invitee_a = authenticated_client_factory(
        identity=_identity_for("kc-invitee-parallel", "parallel@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    invitee_b = authenticated_client_factory(
        identity=_identity_for("kc-invitee-parallel", "parallel@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )

    def _accept(bundle) -> int:
        with bundle.client as client:
            response = client.post("/api/v1/invites/accept", json={"token": token})
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(_accept, (invitee_a, invitee_b)))

    assert statuses.count(200) == 1
    assert statuses.count(409) == 1


def test_accept_invite_allows_user_with_inactive_membership(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-inactive", "owner-inactive@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)
    inactive_user_bundle = authenticated_client_factory(
        identity=_identity_for("kc-inactive-member", "inactive-member@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with inactive_user_bundle.client as client:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Inactive Source Org", "slug": "inactive-source-org"},
        )
        assert created.status_code == 201

    async def _deactivate_current_membership() -> None:
        async with migrated_session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.external_auth_id == "kc-inactive-member")
                )
            ).scalar_one()
            membership = (
                await session.execute(
                    select(Membership).where(Membership.user_id == user.id)
                )
            ).scalar_one()
            membership.is_active = False
            await session.commit()

    run_async(_deactivate_current_membership())

    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Inactive Target Org", "slug": "inactive-target-org"},
        )
        target_org_id = created.json()["id"]
        invited = client.post(
            f"/api/v1/organisations/{target_org_id}/invites",
            json={"email": "inactive-member@example.com", "role": "member"},
        )
        assert invited.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    token = owner_sink.token_for_email("inactive-member@example.com")
    with inactive_user_bundle.client as client:
        accepted = client.post("/api/v1/invites/accept", json={"token": token})
        assert accepted.status_code == 200


def test_invite_accept_rejects_transfer_for_sole_owner(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-sole", "owner-sole@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(monkeypatch)

    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Sole Target", "slug": "org-sole-target"},
        )
        assert create_org.status_code == 201
        target_org_id = create_org.json()["id"]

        invite_response = client.post(
            f"/api/v1/organisations/{target_org_id}/invites",
            json={"email": "invitee-sole@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201

    sole_owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-sole", "invitee-sole@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    sole_owner_client = sole_owner_client_bundle.client

    with sole_owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Sole Source", "slug": "org-sole-source"},
        )
        assert create_org.status_code == 201
        source_org_id = create_org.json()["id"]

    _drain_outbox(migrated_session_factory, monkeypatch)
    token = owner_sink.token_for_email("invitee-sole@example.com")

    with sole_owner_client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["error_code"] == "conflict"

    async def _assert_owner_membership_and_invite_pending() -> None:
        async with migrated_session_factory() as session:
            user_result = await session.execute(
                select(User).where(User.external_auth_id == "kc-invitee-sole")
            )
            user = user_result.scalar_one()

            memberships_result = await session.execute(
                select(Membership).where(Membership.user_id == user.id)
            )
            memberships = list(memberships_result.scalars().all())

            assert len(memberships) == 1
            assert memberships[0].organisation_id == UUID(source_org_id)
            assert memberships[0].role == MembershipRole.OWNER
            assert memberships[0].is_active is True

            invite_result = await session.execute(
                select(Invite).where(
                    Invite.organisation_id == UUID(target_org_id),
                    Invite.email == "invitee-sole@example.com",
                )
            )
            invite = invite_result.scalar_one()
            assert invite.status == InviteStatus.PENDING

    run_async(_assert_owner_membership_and_invite_pending())


def test_superadmin_role_cannot_invite_without_membership(
    authenticated_client_factory,
    migrated_database_url: str,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-2", "owner2@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org C", "slug": "orgc"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]

    super_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            "kc-super",
            "super@example.com",
            roles=["superadmin"],
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    super_client = super_client_bundle.client
    _override_token_sink(monkeypatch)
    with super_client as client:
        response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "new@example.com", "role": "admin"},
        )

    assert response.status_code == 403


def test_old_invite_accept_path_route_is_not_available(
    authenticated_client_factory,
    migrated_database_url: str,
    monkeypatch,
) -> None:
    client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-legacy-path", "legacy@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    client = client_bundle.client
    with client as api_client:
        response = api_client.post("/api/v1/invites/some-token/accept")

    assert response.status_code == 404


def test_invite_accepts_for_first_login_user_without_projection(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-jit", "owner-jit@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(monkeypatch)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org JIT", "slug": "org-jit"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]
        invite_response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "jit-invitee@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201
        assert "token" not in invite_response.json()

    _drain_outbox(migrated_session_factory, monkeypatch)
    token = owner_sink.token_for_email("jit-invitee@example.com")

    invitee_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-jit", "jit-invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    invitee_client = invitee_client_bundle.client
    with invitee_client as client:
        accepted = client.post("/api/v1/invites/accept", json={"token": token})
        assert accepted.status_code == 200

    async def _assert_user_and_membership() -> None:
        async with migrated_session_factory() as session:
            user_result = await session.execute(
                select(User).where(User.external_auth_id == "kc-invitee-jit")
            )
            user = user_result.scalar_one()
            assert user.email == "jit-invitee@example.com"

            membership_result = await session.execute(
                select(Membership).where(Membership.user_id == user.id)
            )
            membership = membership_result.scalar_one()
            assert membership.organisation_id == UUID(org_id)

    run_async(_assert_user_and_membership())


def test_accept_invite_rejects_email_mismatch(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-mismatch", "owner-mismatch@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(monkeypatch)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Mismatch", "slug": "org-mismatch"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]
        invite_response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "expected@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201
        assert "token" not in invite_response.json()

    _drain_outbox(migrated_session_factory, monkeypatch)
    token = owner_sink.token_for_email("expected@example.com")

    wrong_user_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-wrong-email", "wrong@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    wrong_user_client = wrong_user_client_bundle.client
    with wrong_user_client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
    assert response.status_code == 403


def test_accept_invite_rejects_expired_invite(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-expired", "owner-expired@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(monkeypatch)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Expired", "slug": "org-expired"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]

        invite_response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "invitee-expired@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)
    token = owner_sink.token_for_email("invitee-expired@example.com")

    async def _expire_invite() -> None:
        from datetime import UTC, datetime, timedelta

        from app.invites.models.invite import Invite, InviteStatus

        token_hash = sha256(token.encode("utf-8")).hexdigest()
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(Invite).where(
                    Invite.token_hash == token_hash,
                    Invite.status == InviteStatus.PENDING,
                )
            )
            invite = result.scalars().first()
            assert invite is not None
            invite.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()

    run_async(_expire_invite())

    invitee_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-expired", "invitee-expired@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    invitee_client = invitee_client_bundle.client
    with invitee_client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
        assert response.status_code == 409


def test_create_invite_rejects_owner_role(
    authenticated_client_factory,
    migrated_database_url: str,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-role", "owner-role@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    _override_token_sink(monkeypatch)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Role", "slug": "org-role"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]
        response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "invitee-owner@example.com", "role": "owner"},
        )
    assert response.status_code == 422


def test_create_invite_returns_single_resource_contract(
    authenticated_client_factory,
    migrated_database_url: str,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-contract", "owner-contract@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    _override_token_sink(monkeypatch)
    invite_email = "contract-invitee@example.com"
    invite_role = "member"

    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Invite Contract Org", "slug": "invite-contract-org"},
        )
        assert create_org.status_code == 201
        organisation_id = create_org.json()["id"]

        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": invite_email, "role": invite_role},
        )

    assert response.status_code == 201
    body = response.json()
    assert "invite" not in body
    assert "id" in body
    assert "email" in body
    assert "organisation_id" in body
    assert "role" in body
    assert "status" in body
    assert "expires_at" in body
    assert "created_at" in body
    assert "updated_at" in body
    assert body["email"] == invite_email
    assert body["organisation_id"] == organisation_id
    assert body["role"] == invite_role
    assert body["status"] == "pending"


def test_create_invite_delivery_failure_keeps_invite_and_audit_event(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-create-fail", "owner-create-fail@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    _override_failing_token_sink(monkeypatch)
    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Acme", "slug": "invite-create-fail"},
        )
        organisation_id = created.json()["id"]
        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee-create-fail@example.com", "role": "member"},
        )
        assert response.status_code == 201
        invite_id = response.json()["id"]

    async def _assert_persisted() -> None:
        async with migrated_session_factory() as session:
            invite_result = await session.execute(
                select(Invite).where(Invite.id == UUID(invite_id))
            )
            invite = invite_result.scalar_one()
            assert invite.status == InviteStatus.PENDING
            audit_result = await session.execute(
                select(AuditEvent).where(
                    AuditEvent.target_id == invite.id,
                    AuditEvent.action == "invite_created",
                )
            )
            audit_event = audit_result.scalar_one_or_none()
            assert audit_event is not None
            assert audit_event.action == "invite_created"
            assert audit_event.target_id == invite.id

    run_async(_assert_persisted())


def test_resend_invite_delivery_failure_updates_outbox_state(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-resend-fail", "owner-resend-fail@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)
    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Acme", "slug": "invite-resend-fail"},
        )
        organisation_id = created.json()["id"]
        invite_response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee-resend-fail@example.com", "role": "member"},
        )
        invite_id = invite_response.json()["id"]
        _drain_outbox(migrated_session_factory, monkeypatch)
    initial_token = owner_sink.token_for_email("invitee-resend-fail@example.com")

    _override_failing_token_sink(monkeypatch)
    with owner_bundle.client as client:
        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend"
        )
        assert response.status_code == 200
        assert "token" not in response.json()

    _drain_outbox(migrated_session_factory, monkeypatch)

    async def _assert_resend_persisted() -> None:
        async with migrated_session_factory() as session:
            invite = (
                await session.execute(
                    select(Invite).where(Invite.id == UUID(invite_id))
                )
            ).scalar_one()
            assert (
                invite.token_hash != sha256(initial_token.encode("utf-8")).hexdigest()
            )
            audit_event = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.target_id == invite.id,
                        AuditEvent.action == "invite_resent",
                    )
                )
            ).scalar_one_or_none()
            assert audit_event is not None
            outbox_event = (
                (
                    await session.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_id == invite.id,
                            OutboxEvent.event_type
                            == OutboxEventType.INVITE_RESEND.value,
                        )
                    )
                )
                .scalars()
                .all()[-1]
            )
            assert outbox_event.attempts >= 1
            assert outbox_event.status in {
                OutboxStatus.PENDING.value,
                OutboxStatus.FAILED.value,
            }
            assert outbox_event.last_error is not None

    run_async(_assert_resend_persisted())


def test_create_invite_returns_404_for_missing_organisation(
    authenticated_client_factory,
    migrated_database_url: str,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-missing-org", "owner-missing-org@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    _override_token_sink(monkeypatch)
    with owner_client as client:
        response = client.post(
            "/api/v1/organisations/00000000-0000-0000-0000-000000000001/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    assert response.status_code == 404


def test_create_invite_returns_403_when_organisation_exists_but_actor_has_no_access(
    authenticated_client_factory,
    migrated_database_url: str,
    monkeypatch,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-no-access", "owner-no-access@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(monkeypatch)

    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Invite Access Org", "slug": "invite-access-org"},
        )
        assert create_org.status_code == 201
        organisation_id = create_org.json()["id"]

    outsider_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-outsider-invite", "outsider-invite@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    outsider_client = outsider_client_bundle.client
    _override_token_sink(monkeypatch)

    with outsider_client as client:
        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    assert response.status_code == 403
    assert owner_sink._tokens_by_email == {}


def test_suspended_user_cannot_create_invite(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations", json={"name": "Acme", "slug": "invite-susp-user"}
        )
        organisation_id = created.json()["id"]

    async def _suspend_owner() -> None:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(User).where(User.external_auth_id == "kc-owner")
            )
            user = result.scalar_one()
            user.status = UserStatus.SUSPENDED
            await session.commit()

    run_async(_suspend_owner())

    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with owner_bundle.client as client:
        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert response.status_code == 403


def test_suspended_organisation_blocks_invite_acceptance(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-org", "owner-org@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)
    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations", json={"name": "Acme", "slug": "invite-org-susp"}
        )
        organisation_id = created.json()["id"]
        client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        _drain_outbox(migrated_session_factory, monkeypatch)
    token = owner_sink.token_for_email("invitee@example.com")

    async def _suspend_org() -> None:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(Organisation).where(Organisation.id == UUID(organisation_id))
            )
            org = result.scalar_one()
            org.status = OrganisationStatus.SUSPENDED
            await session.commit()

    run_async(_suspend_org())

    invitee_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee", "invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with invitee_bundle.client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
        assert response.status_code == 403


def test_unverified_email_cannot_accept_invite(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    owner_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-unver", "owner-unver@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(monkeypatch)
    with owner_bundle.client as client:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Acme Unverified", "slug": "acme-unverified-invite"},
        )
        assert created.status_code == 201
        organisation_id = created.json()["id"]
        invited = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee-unverified@example.com", "role": "member"},
        )
        assert invited.status_code == 201
        _drain_outbox(migrated_session_factory, monkeypatch)
    token = owner_sink.token_for_email("invitee-unverified@example.com")

    invitee_bundle = authenticated_client_factory(
        identity=_identity_for(
            "kc-invitee-unverified",
            "invitee-unverified@example.com",
            email_verified=False,
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with invitee_bundle.client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")
