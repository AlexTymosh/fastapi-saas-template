from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.users.models.user import User
from tests.api.test_users_organisations import _identity_for
from tests.helpers.asyncio_runner import run_async


@dataclass(frozen=True)
class OrganisationFixture:
    id: str
    name: str
    slug: str


def _assert_problem_details(response, *, expected_status: int | set[int]) -> None:
    expected = (
        expected_status if isinstance(expected_status, set) else {expected_status}
    )
    assert response.status_code in expected
    assert response.status_code < 200 or response.status_code >= 300
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["status"] == response.status_code
    assert "title" in payload
    assert "detail" in payload


def _client_bundle(authenticated_client_factory, database_url: str, identity):
    return authenticated_client_factory(
        identity=identity,
        database_url=database_url,
        redis_url=None,
    )


def _provision_user(
    authenticated_client_factory, database_url: str, *, identity
) -> None:
    bundle = _client_bundle(authenticated_client_factory, database_url, identity)
    with bundle.client as client:
        response = client.get("/api/v1/users/me")
    assert response.status_code == 200


def _create_organisation(
    authenticated_client_factory,
    database_url: str,
    *,
    owner_identity,
    name: str,
    slug: str,
) -> OrganisationFixture:
    bundle = _client_bundle(authenticated_client_factory, database_url, owner_identity)
    with bundle.client as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": name, "slug": slug},
        )
    assert response.status_code == 201
    payload = response.json()
    return OrganisationFixture(
        id=payload["id"], name=payload["name"], slug=payload["slug"]
    )


def _insert_membership(
    migrated_session_factory,
    *,
    external_auth_id: str,
    organisation_id: str,
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
                organisation_id=UUID(organisation_id),
                role=role,
            )
            session.add(membership)
            await session.commit()
            await session.refresh(membership)
            return membership.id

    return run_async(_insert())


def _get_organisation(migrated_session_factory, organisation_id: str) -> Organisation:
    async def _fetch() -> Organisation:
        async with migrated_session_factory() as session:
            return (
                await session.execute(
                    select(Organisation).where(Organisation.id == UUID(organisation_id))
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


def _get_invite(migrated_session_factory, invite_id: str) -> Invite:
    async def _fetch() -> Invite:
        async with migrated_session_factory() as session:
            return (
                await session.execute(
                    select(Invite).where(Invite.id == UUID(invite_id))
                )
            ).scalar_one()

    return run_async(_fetch())


def test_org_a_user_cannot_read_or_update_org_b(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    org_a_owner = _identity_for("kc-bola-org-a-owner", "bola-org-a-owner@example.com")
    org_b_owner = _identity_for("kc-bola-org-b-owner", "bola-org-b-owner@example.com")
    _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=org_a_owner,
        name="BOLA Org A",
        slug="bola-org-a",
    )
    org_b = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=org_b_owner,
        name="BOLA Org B",
        slug="bola-org-b",
    )

    org_a_bundle = _client_bundle(
        authenticated_client_factory, migrated_database_url, org_a_owner
    )
    with org_a_bundle.client as client:
        read_response = client.get(f"/api/v1/organisations/{org_b.id}")
        update_response = client.patch(
            f"/api/v1/organisations/{org_b.id}",
            json={"name": "Compromised Org B", "slug": "compromised-org-b"},
        )

    _assert_problem_details(read_response, expected_status=403)
    _assert_problem_details(update_response, expected_status=403)
    persisted_org_b = _get_organisation(migrated_session_factory, org_b.id)
    assert persisted_org_b.name == org_b.name
    assert persisted_org_b.slug == org_b.slug
    assert persisted_org_b.deleted_at is None


def test_non_owners_cannot_delete_other_organisation(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a = _identity_for("kc-delete-owner-a", "delete-owner-a@example.com")
    admin_a = _identity_for("kc-delete-admin-a", "delete-admin-a@example.com")
    member_a = _identity_for("kc-delete-member-a", "delete-member-a@example.com")
    non_member = _identity_for("kc-delete-non-member", "delete-non-member@example.com")
    owner_b = _identity_for("kc-delete-owner-b", "delete-owner-b@example.com")

    org_a = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_a,
        name="Delete Org A",
        slug="delete-org-a-bola",
    )
    org_b = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_b,
        name="Delete Org B",
        slug="delete-org-b-bola",
    )
    for identity in (admin_a, member_a, non_member):
        _provision_user(
            authenticated_client_factory, migrated_database_url, identity=identity
        )
    _insert_membership(
        migrated_session_factory,
        external_auth_id=admin_a.external_auth_id,
        organisation_id=org_a.id,
        role=MembershipRole.ADMIN,
    )
    _insert_membership(
        migrated_session_factory,
        external_auth_id=member_a.external_auth_id,
        organisation_id=org_a.id,
        role=MembershipRole.MEMBER,
    )

    for actor in (admin_a, member_a, non_member):
        bundle = _client_bundle(
            authenticated_client_factory, migrated_database_url, actor
        )
        with bundle.client as client:
            response = client.delete(f"/api/v1/organisations/{org_b.id}")
        _assert_problem_details(response, expected_status=403)

    persisted_org_b = _get_organisation(migrated_session_factory, org_b.id)
    assert persisted_org_b.deleted_at is None
    assert persisted_org_b.slug == org_b.slug


def test_org_a_user_cannot_read_org_b_directory(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_a = _identity_for("kc-dir-bola-owner-a", "dir-bola-owner-a@example.com")
    owner_b = _identity_for("kc-dir-bola-owner-b", "dir-bola-owner-b@example.com")
    _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_a,
        name="Directory Org A",
        slug="directory-org-a-bola",
    )
    org_b = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_b,
        name="Directory Org B",
        slug="directory-org-b-bola",
    )

    bundle = _client_bundle(
        authenticated_client_factory, migrated_database_url, owner_a
    )
    with bundle.client as client:
        response = client.get(f"/api/v1/organisations/{org_b.id}/directory")

    _assert_problem_details(response, expected_status=403)


def test_member_cannot_read_management_memberships(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = _identity_for("kc-management-owner", "management-owner@example.com")
    member = _identity_for("kc-management-member", "management-member@example.com")
    org = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner,
        name="Management Org",
        slug="management-org-bola",
    )
    _provision_user(
        authenticated_client_factory, migrated_database_url, identity=member
    )
    _insert_membership(
        migrated_session_factory,
        external_auth_id=member.external_auth_id,
        organisation_id=org.id,
        role=MembershipRole.MEMBER,
    )

    member_bundle = _client_bundle(
        authenticated_client_factory, migrated_database_url, member
    )
    with member_bundle.client as client:
        response = client.get(f"/api/v1/organisations/{org.id}/memberships")

    _assert_problem_details(response, expected_status=403)


def test_cross_org_membership_id_cannot_be_changed_or_removed(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a = _identity_for(
        "kc-cross-membership-owner-a", "cross-membership-owner-a@example.com"
    )
    owner_b = _identity_for(
        "kc-cross-membership-owner-b", "cross-membership-owner-b@example.com"
    )
    member_b = _identity_for(
        "kc-cross-membership-member-b", "cross-membership-member-b@example.com"
    )
    org_a = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_a,
        name="Cross Membership Org A",
        slug="cross-membership-org-a",
    )
    org_b = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_b,
        name="Cross Membership Org B",
        slug="cross-membership-org-b",
    )
    _provision_user(
        authenticated_client_factory, migrated_database_url, identity=member_b
    )
    membership_b_id = _insert_membership(
        migrated_session_factory,
        external_auth_id=member_b.external_auth_id,
        organisation_id=org_b.id,
        role=MembershipRole.MEMBER,
    )

    owner_a_bundle = _client_bundle(
        authenticated_client_factory, migrated_database_url, owner_a
    )
    with owner_a_bundle.client as client:
        change_response = client.patch(
            f"/api/v1/organisations/{org_a.id}/memberships/{membership_b_id}/role",
            json={"role": "admin"},
        )
        delete_response = client.delete(
            f"/api/v1/organisations/{org_a.id}/memberships/{membership_b_id}"
        )

    _assert_problem_details(change_response, expected_status=404)
    _assert_problem_details(delete_response, expected_status=404)
    persisted_membership_b = _get_membership(migrated_session_factory, membership_b_id)
    assert persisted_membership_b.organisation_id == UUID(org_b.id)
    assert persisted_membership_b.role == MembershipRole.MEMBER
    assert persisted_membership_b.is_active is True


def test_org_a_user_cannot_create_invite_in_org_b(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a = _identity_for(
        "kc-create-invite-owner-a", "create-invite-owner-a@example.com"
    )
    owner_b = _identity_for(
        "kc-create-invite-owner-b", "create-invite-owner-b@example.com"
    )
    _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_a,
        name="Create Invite Org A",
        slug="create-invite-org-a",
    )
    org_b = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_b,
        name="Create Invite Org B",
        slug="create-invite-org-b",
    )

    owner_a_bundle = _client_bundle(
        authenticated_client_factory, migrated_database_url, owner_a
    )
    with owner_a_bundle.client as client:
        response = client.post(
            f"/api/v1/organisations/{org_b.id}/invites",
            json={"email": "cross-create-invite@example.com", "role": "member"},
        )

    _assert_problem_details(response, expected_status=403)

    async def _count_matching_invites() -> int:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(Invite).where(
                    Invite.organisation_id == UUID(org_b.id),
                    Invite.email == "cross-create-invite@example.com",
                )
            )
            return len(result.scalars().all())

    assert run_async(_count_matching_invites()) == 0


def test_cross_org_invite_id_cannot_be_revoked_or_resent(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_a = _identity_for(
        "kc-cross-invite-owner-a", "cross-invite-owner-a@example.com"
    )
    owner_b = _identity_for(
        "kc-cross-invite-owner-b", "cross-invite-owner-b@example.com"
    )
    org_a = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_a,
        name="Cross Invite Org A",
        slug="cross-invite-org-a",
    )
    org_b = _create_organisation(
        authenticated_client_factory,
        migrated_database_url,
        owner_identity=owner_b,
        name="Cross Invite Org B",
        slug="cross-invite-org-b",
    )

    owner_b_bundle = _client_bundle(
        authenticated_client_factory, migrated_database_url, owner_b
    )
    with owner_b_bundle.client as client:
        invite_response = client.post(
            f"/api/v1/organisations/{org_b.id}/invites",
            json={"email": "cross-invite-target@example.com", "role": "member"},
        )
    assert invite_response.status_code == 201
    invite_id = invite_response.json()["id"]
    original_invite = _get_invite(migrated_session_factory, invite_id)

    owner_a_bundle = _client_bundle(
        authenticated_client_factory, migrated_database_url, owner_a
    )
    with owner_a_bundle.client as client:
        revoke_response = client.delete(
            f"/api/v1/organisations/{org_a.id}/invites/{invite_id}"
        )
        resend_response = client.post(
            f"/api/v1/organisations/{org_a.id}/invites/{invite_id}/resend"
        )

    _assert_problem_details(revoke_response, expected_status=404)
    _assert_problem_details(resend_response, expected_status=404)
    persisted_invite = _get_invite(migrated_session_factory, invite_id)
    assert persisted_invite.organisation_id == UUID(org_b.id)
    assert persisted_invite.status == InviteStatus.PENDING
    assert persisted_invite.revoked_at is None
    assert persisted_invite.revoked_by_user_id is None
    assert persisted_invite.token_hash == original_invite.token_hash
