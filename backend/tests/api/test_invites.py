from __future__ import annotations

from app.core.auth import AuthenticatedPrincipal


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


def test_invite_accept_transfers_membership(
    authenticated_client_factory,
    migrated_database_url: str,
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
        token = invite_response.json()["token"]

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
