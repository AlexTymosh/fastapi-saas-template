from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.users.models.user import User
from tests.api.test_users_organisations import _identity_for
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security, pytest.mark.authz]


def _assert_problem_details(response, *, expected_status: int) -> None:
    assert response.status_code == expected_status
    assert response.status_code < 200 or response.status_code >= 300
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == expected_status
    assert body["instance"]
    assert body["error_code"]
    assert "request_id" in body


def _provision(authenticated_client_factory, database_url: str, identity) -> None:
    bundle = authenticated_client_factory(
        identity=identity,
        database_url=database_url,
        redis_url=None,
    )
    with bundle.client as client:
        response = client.get("/api/v1/users/me")
        assert response.status_code == 200


def _create_organisation(
    authenticated_client_factory,
    database_url: str,
    identity,
    *,
    name: str,
    slug: str,
) -> UUID:
    bundle = authenticated_client_factory(
        identity=identity,
        database_url=database_url,
        redis_url=None,
    )
    with bundle.client as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": name, "slug": slug},
        )
        assert response.status_code == 201
        return UUID(response.json()["id"])


def _create_two_organisations(authenticated_client_factory, database_url: str):
    owner_a = _identity_for("kc-bola-owner-a", "bola-owner-a@example.com")
    owner_b = _identity_for("kc-bola-owner-b", "bola-owner-b@example.com")
    org_a_id = _create_organisation(
        authenticated_client_factory,
        database_url,
        owner_a,
        name="BOLA Org A",
        slug="bola-org-a",
    )
    org_b_id = _create_organisation(
        authenticated_client_factory,
        database_url,
        owner_b,
        name="BOLA Org B",
        slug="bola-org-b",
    )
    return owner_a, owner_b, org_a_id, org_b_id


def _add_membership(
    migrated_session_factory,
    *,
    external_auth_id: str,
    organisation_id: UUID,
    role: MembershipRole,
) -> UUID:
    async def _insert() -> UUID:
        async with migrated_session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.external_auth_id == external_auth_id)
                )
            ).scalar_one()
            membership = Membership(
                user_id=user.id,
                organisation_id=organisation_id,
                role=role,
            )
            session.add(membership)
            await session.commit()
            await session.refresh(membership)
            return membership.id

    return run_async(_insert())


def _get_organisation(migrated_session_factory, organisation_id: UUID) -> Organisation:
    async def _fetch() -> Organisation:
        async with migrated_session_factory() as session:
            return (
                await session.execute(
                    select(Organisation).where(Organisation.id == organisation_id)
                )
            ).scalar_one()

    return run_async(_fetch())


def _get_membership(migrated_session_factory, membership_id: UUID) -> Membership:
    async def _fetch() -> Membership:
        async with migrated_session_factory() as session:
            return (
                await session.execute(
                    select(Membership).where(Membership.id == membership_id)
                )
            ).scalar_one()

    return run_async(_fetch())


def _get_invite(migrated_session_factory, invite_id: UUID) -> Invite:
    async def _fetch() -> Invite:
        async with migrated_session_factory() as session:
            return (
                await session.execute(select(Invite).where(Invite.id == invite_id))
            ).scalar_one()

    return run_async(_fetch())


def test_member_of_org_a_cannot_read_org_b(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_a, _, _, org_b_id = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )

    bundle = authenticated_client_factory(
        identity=owner_a, database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.get(f"/api/v1/organisations/{org_b_id}")

    _assert_problem_details(response, expected_status=403)


def test_member_of_org_a_cannot_update_org_b(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a, _, _, org_b_id = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )
    before = _get_organisation(migrated_session_factory, org_b_id)

    bundle = authenticated_client_factory(
        identity=owner_a, database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.patch(
            f"/api/v1/organisations/{org_b_id}",
            json={"name": "BOLA Org B Changed", "slug": "bola-org-b-changed"},
        )

    _assert_problem_details(response, expected_status=403)
    after = _get_organisation(migrated_session_factory, org_b_id)
    assert after.name == before.name
    assert after.slug == before.slug
    assert after.deleted_at is None


@pytest.mark.parametrize(
    ("external_auth_id", "email", "role"),
    [
        ("kc-bola-admin-a", "bola-admin-a@example.com", MembershipRole.ADMIN),
        ("kc-bola-member-a", "bola-member-a@example.com", MembershipRole.MEMBER),
        ("kc-bola-nonmember", "bola-nonmember@example.com", None),
    ],
)
def test_admin_member_or_non_member_cannot_delete_foreign_organisation(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    external_auth_id: str,
    email: str,
    role: MembershipRole | None,
) -> None:
    _, _, org_a_id, org_b_id = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )
    identity = _identity_for(external_auth_id, email)
    _provision(authenticated_client_factory, migrated_database_url, identity)
    if role is not None:
        _add_membership(
            migrated_session_factory,
            external_auth_id=external_auth_id,
            organisation_id=org_a_id,
            role=role,
        )

    bundle = authenticated_client_factory(
        identity=identity, database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.request(
            "DELETE",
            f"/api/v1/organisations/{org_b_id}",
            json={"reason": "cross-tenant delete attempt"},
        )

    _assert_problem_details(response, expected_status=403)
    after = _get_organisation(migrated_session_factory, org_b_id)
    assert after.deleted_at is None


def test_member_of_org_a_cannot_read_org_b_directory(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_a, _, _, org_b_id = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )

    bundle = authenticated_client_factory(
        identity=owner_a, database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.get(f"/api/v1/organisations/{org_b_id}/directory")

    _assert_problem_details(response, expected_status=403)


def test_member_cannot_read_management_memberships(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    _, _, org_a_id, _ = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )
    member = _identity_for("kc-bola-member-list", "bola-member-list@example.com")
    _provision(authenticated_client_factory, migrated_database_url, member)
    _add_membership(
        migrated_session_factory,
        external_auth_id="kc-bola-member-list",
        organisation_id=org_a_id,
        role=MembershipRole.MEMBER,
    )

    bundle = authenticated_client_factory(
        identity=member, database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.get(f"/api/v1/organisations/{org_a_id}/memberships")

    _assert_problem_details(response, expected_status=403)


def test_membership_id_from_another_org_cannot_be_used_under_actor_org_path(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a, _, org_a_id, org_b_id = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )
    target = _identity_for(
        "kc-bola-member-b-delete", "bola-member-b-delete@example.com"
    )
    _provision(authenticated_client_factory, migrated_database_url, target)
    target_membership_id = _add_membership(
        migrated_session_factory,
        external_auth_id="kc-bola-member-b-delete",
        organisation_id=org_b_id,
        role=MembershipRole.MEMBER,
    )

    bundle = authenticated_client_factory(
        identity=owner_a, database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        role_response = client.patch(
            f"/api/v1/organisations/{org_a_id}/memberships/{target_membership_id}/role",
            json={"role": "admin"},
        )
        delete_response = client.request(
            "DELETE",
            f"/api/v1/organisations/{org_a_id}/memberships/{target_membership_id}",
            json={"reason": "cross-tenant membership removal attempt"},
        )

    _assert_problem_details(role_response, expected_status=404)
    _assert_problem_details(delete_response, expected_status=404)
    target_membership = _get_membership(migrated_session_factory, target_membership_id)
    assert target_membership.organisation_id == org_b_id
    assert target_membership.role == MembershipRole.MEMBER
    assert target_membership.is_active is True


def test_member_of_org_a_cannot_create_invite_in_org_b(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a, _, _, org_b_id = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )

    bundle = authenticated_client_factory(
        identity=owner_a, database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.post(
            f"/api/v1/organisations/{org_b_id}/invites",
            json={"email": "cross-tenant-invite@example.com", "role": "member"},
        )

    _assert_problem_details(response, expected_status=403)

    async def _count_invites() -> int:
        async with migrated_session_factory() as session:
            return int(
                (
                    await session.execute(
                        select(func.count(Invite.id)).where(
                            Invite.organisation_id == org_b_id,
                            Invite.email == "cross-tenant-invite@example.com",
                        )
                    )
                ).scalar_one()
            )

    assert run_async(_count_invites()) == 0


def test_invite_id_from_another_org_cannot_be_revoked_or_resent_under_actor_org_path(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a, owner_b, org_a_id, org_b_id = _create_two_organisations(
        authenticated_client_factory, migrated_database_url
    )
    owner_b_bundle = authenticated_client_factory(
        identity=owner_b, database_url=migrated_database_url, redis_url=None
    )
    with owner_b_bundle.client as client:
        created = client.post(
            f"/api/v1/organisations/{org_b_id}/invites",
            json={"email": "foreign-invite@example.com", "role": "member"},
        )
        assert created.status_code == 201
        invite_id = UUID(created.json()["id"])

    before = _get_invite(migrated_session_factory, invite_id)

    owner_a_bundle = authenticated_client_factory(
        identity=owner_a, database_url=migrated_database_url, redis_url=None
    )
    with owner_a_bundle.client as client:
        revoke_response = client.request(
            "DELETE",
            f"/api/v1/organisations/{org_a_id}/invites/{invite_id}",
            json={"reason": "cross-tenant invite revoke attempt"},
        )
        resend_response = client.post(
            f"/api/v1/organisations/{org_a_id}/invites/{invite_id}/resend"
        )

    _assert_problem_details(revoke_response, expected_status=404)
    _assert_problem_details(resend_response, expected_status=404)
    after = _get_invite(migrated_session_factory, invite_id)
    assert after.organisation_id == org_b_id
    assert after.status == InviteStatus.PENDING
    assert after.token_hash == before.token_hash
    assert after.expires_at == before.expires_at
    assert after.revoked_at is None
    assert after.revoked_by_user_id is None
