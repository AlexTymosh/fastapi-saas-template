from __future__ import annotations

from app.core.auth import AuthenticatedPrincipal
from app.memberships.models.membership import MembershipRole


def _identity(
    external_auth_id: str,
    email: str,
    *,
    platform_roles: frozenset[str] = frozenset(),
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id=external_auth_id,
        email=email,
        email_verified=True,
        platform_roles=platform_roles,
    )


def test_accepting_invite_transfers_membership_atomically(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client, owner_auth = authenticated_client_factory(
        identity=_identity("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner_client as client:
        org1 = client.post(
            "/api/v1/organisations",
            json={"name": "Org One", "slug": "org-one"},
        )
        assert org1.status_code == 201

        owner_auth.set_identity(_identity("kc-super", "super@example.com", platform_roles=frozenset({"superadmin"})))
        org2 = client.post(
            "/api/v1/organisations",
            json={"name": "Org Two", "slug": "org-two"},
        )
        assert org2.status_code == 201

        owner_auth.set_identity(_identity("kc-owner", "owner@example.com"))
        invite = client.post(
            f"/api/v1/organisations/{org2.json()['id']}/invites",
            json={"email": "owner@example.com", "role": MembershipRole.MEMBER.value},
        )
        assert invite.status_code == 201

        accepted = client.post(f"/api/v1/invites/{invite.json()['token']}/accept")
        assert accepted.status_code == 200

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        assert me.json()["membership"]["organisation_id"] == org2.json()["id"]


def test_invite_acceptance_requires_email_match(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    client, auth = authenticated_client_factory(
        identity=_identity("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with client:
        org = client.post(
            "/api/v1/organisations",
            json={"name": "Org", "slug": "org"},
        )
        assert org.status_code == 201
        invite = client.post(
            f"/api/v1/organisations/{org.json()['id']}/invites",
            json={"email": "target@example.com", "role": MembershipRole.MEMBER.value},
        )
        assert invite.status_code == 201

        auth.set_identity(_identity("kc-other", "other@example.com"))
        accepted = client.post(f"/api/v1/invites/{invite.json()['token']}/accept")
        assert accepted.status_code == 403
