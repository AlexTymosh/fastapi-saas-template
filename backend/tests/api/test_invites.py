from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.core.auth import AuthenticatedPrincipal
from app.invites.services.invites import InviteService
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


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


def _create_invite_token(
    *,
    migrated_session_factory,
    actor_external_auth_id: str,
    organisation_id: str,
    email: str,
    role: MembershipRole = MembershipRole.MEMBER,
) -> str:
    async def _create() -> str:
        async with migrated_session_factory() as session:
            actor_result = await session.execute(
                select(User).where(User.external_auth_id == actor_external_auth_id)
            )
            actor = actor_result.scalar_one()
            invite_service = InviteService(session)
            _invite, token = await invite_service.create_invite(
                organisation_id=UUID(organisation_id),
                actor_user_id=actor.id,
                role=role,
                email=email,
                actor_is_superadmin=False,
            )
            return token

    return run_async(_create())


def test_invite_accept_transfers_membership(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org A", "slug": "orga"},
        )
        assert create_org.status_code == 201
        org_a = create_org.json()["id"]

    invitee_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-invitee", "invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with invitee_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org B", "slug": "orgb"},
        )
        assert create_org.status_code == 201

    with owner_client as client:
        invite_response = client.post(
            f"/api/v1/organisations/{org_a}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201
        assert "token" not in invite_response.json()

    token = _create_invite_token(
        migrated_session_factory=migrated_session_factory,
        actor_external_auth_id="kc-owner",
        organisation_id=org_a,
        email="invitee@example.com",
    )

    with invitee_client as client:
        accepted = client.post(f"/api/v1/invites/{token}/accept")
        assert accepted.status_code == 200

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        assert me.json()["membership"]["organisation_id"] == org_a


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

    token = _create_invite_token(
        migrated_session_factory=migrated_session_factory,
        actor_external_auth_id="kc-owner-jit",
        organisation_id=org_id,
        email="jit-invitee@example.com",
    )

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
    migrated_session_factory,
) -> None:
    owner_client, _ = authenticated_client_factory(
        identity=_identity_for("kc-owner-mismatch", "owner-mismatch@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
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

    token = _create_invite_token(
        migrated_session_factory=migrated_session_factory,
        actor_external_auth_id="kc-owner-mismatch",
        organisation_id=org_id,
        email="expected@example.com",
    )

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
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Expired", "slug": "org-expired"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]

    token = _create_invite_token(
        migrated_session_factory=migrated_session_factory,
        actor_external_auth_id="kc-owner-expired",
        organisation_id=org_id,
        email="invitee-expired@example.com",
    )

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
