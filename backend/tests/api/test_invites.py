from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.core.auth import AuthenticatedPrincipal
from app.invites.services.delivery import get_invite_token_sink
from app.memberships.models.membership import Membership
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


class InMemoryInviteTokenSink:
    def __init__(self) -> None:
        self._tokens_by_email: dict[str, str] = {}

    async def deliver(self, *, invite, raw_token: str) -> None:
        self._tokens_by_email[invite.email.lower()] = raw_token

    def token_for_email(self, email: str) -> str:
        return self._tokens_by_email[email.lower()]


def _identity_for(
    external_auth_id: str,
    email: str,
    roles: list[str] | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id=external_auth_id,
        email=email,
        email_verified=True,
        platform_roles=roles or [],
    )


def _override_token_sink(test_client) -> InMemoryInviteTokenSink:
    sink = InMemoryInviteTokenSink()
    test_client.app.dependency_overrides[get_invite_token_sink] = lambda: sink
    return sink


def test_invite_accept_transfers_membership(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    destination_owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    destination_sink = _override_token_sink(destination_owner_client)
    with destination_owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org A", "slug": "orga"},
        )
        assert create_org.status_code == 201
        org_a = create_org.json()["id"]

    source_owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-source-owner", "source-owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    source_sink = _override_token_sink(source_owner_client)
    with source_owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org B", "slug": "orgb"},
        )
        assert create_org.status_code == 201
        org_b = create_org.json()["id"]
        seed_member_invite = client.post(
            f"/api/v1/organisations/{org_b}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert seed_member_invite.status_code == 201

    invitee_client, invitee_session_factory = authenticated_client_factory(
        identity=_identity_for("kc-invitee", "invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )

    source_token = source_sink.token_for_email("invitee@example.com")
    with invitee_client as client:
        first_accept = client.post(f"/api/v1/invites/{source_token}/accept")
        assert first_accept.status_code == 200

    with destination_owner_client as client:
        invite_response = client.post(
            f"/api/v1/organisations/{org_a}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201
        assert "token" not in invite_response.json()

    token = destination_sink.token_for_email("invitee@example.com")

    with invitee_client as client:
        accepted = client.post(f"/api/v1/invites/{token}/accept")
        assert accepted.status_code == 200

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        assert me.json()["membership"]["organisation_id"] == org_a
        assert me.json()["membership"]["role"] == "member"

    async def _assert_transfer_state() -> None:
        async with invitee_session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.external_auth_id == "kc-invitee")
                )
            ).scalar_one()
            memberships = (
                await session.execute(
                    select(Membership).where(Membership.user_id == user.id)
                )
            ).scalars().all()
            by_org = {str(m.organisation_id): m for m in memberships}
            assert by_org[org_b].is_active is False
            assert by_org[org_a].is_active is True

    run_async(_assert_transfer_state())


def test_invite_accept_rejects_transfer_for_sole_owner(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-sole", "owner-sole@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(owner_client)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Sole", "slug": "org-sole"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]
        invite_response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "owner-sole@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201

    token = owner_sink.token_for_email("owner-sole@example.com")

    with owner_client as client:
        response = client.post(f"/api/v1/invites/{token}/accept")
        assert response.status_code == 409


def test_superadmin_can_invite_without_membership(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-2", "owner2@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org C", "slug": "orgc"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]

    super_client, _ = authenticated_client_factory(
        identity=_identity_for(
            "kc-super",
            "super@example.com",
            roles=["superadmin"],
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    _override_token_sink(super_client)
    with super_client as client:
        response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "new@example.com", "role": "admin"},
        )

    assert response.status_code == 201


def test_invite_accepts_for_first_login_user_without_projection(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-jit", "owner-jit@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(owner_client)
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

    token = owner_sink.token_for_email("jit-invitee@example.com")

    invitee_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-invitee-jit", "jit-invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with invitee_client as client:
        accepted = client.post(f"/api/v1/invites/{token}/accept")
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
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-mismatch", "owner-mismatch@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(owner_client)
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

    token = owner_sink.token_for_email("expected@example.com")

    wrong_user_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-wrong-email", "wrong@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with wrong_user_client as client:
        response = client.post(f"/api/v1/invites/{token}/accept")
    assert response.status_code == 403


def test_accept_invite_rejects_expired_invite(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-expired", "owner-expired@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(owner_client)
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

    invitee_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-invitee-expired", "invitee-expired@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with invitee_client as client:
        response = client.post(f"/api/v1/invites/{token}/accept")
        assert response.status_code == 409


def test_create_invite_rejects_owner_role(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-role", "owner-role@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    _override_token_sink(owner_client)
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


def test_create_invite_returns_404_for_missing_organisation(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-missing-org", "owner-missing-org@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    _override_token_sink(owner_client)
    with owner_client as client:
        response = client.post(
            "/api/v1/organisations/00000000-0000-0000-0000-000000000001/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    assert response.status_code == 404


def test_create_invite_returns_403_when_organisation_exists_but_actor_has_no_access(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-no-access", "owner-no-access@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_sink = _override_token_sink(owner_client)

    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Invite Access Org", "slug": "invite-access-org"},
        )
        assert create_org.status_code == 201
        organisation_id = create_org.json()["id"]

    outsider_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-outsider-invite", "outsider-invite@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    _override_token_sink(outsider_client)

    with outsider_client as client:
        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    assert response.status_code == 403
    assert owner_sink._tokens_by_email == {}
