from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

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


def test_directory_privacy_and_tenant_role_visibility(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = _identity_for(
        "kc-dir-owner", "dir-owner@example.com", first_name="Owner", last_name="Person"
    )
    member = _identity_for(
        "kc-dir-member", "john@example.com", first_name="  ", last_name="  "
    )
    _provision(authenticated_client_factory, migrated_database_url, owner)
    _provision(authenticated_client_factory, migrated_database_url, member)

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations", json={"name": "Dir Org", "slug": "dir-org"}
        )
        organisation_id = create.json()["id"]

    async def _insert_member() -> None:
        async with migrated_session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.external_auth_id == "kc-dir-member")
                )
            ).scalar_one()
            session.add(
                Membership(
                    user_id=user.id,
                    organisation_id=UUID(organisation_id),
                    role=MembershipRole.MEMBER,
                )
            )
            await session.commit()

    run_async(_insert_member())

    with owner_bundle.client as client:
        response = client.get(f"/api/v1/organisations/{organisation_id}/directory")
        assert response.status_code == 200
        payload = response.json()
        assert {"data", "meta", "links"} <= payload.keys()
        for item in payload["data"]:
            assert set(item.keys()) == {"display_name", "tenant_role"}
            assert item["tenant_role"] in {"owner", "admin", "member"}
            assert item["display_name"]


def test_delete_membership_returns_204_and_deactivates(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner = _identity_for("kc-del-owner", "del-owner@example.com")
    member = _identity_for("kc-del-member", "del-member@example.com")
    _provision(authenticated_client_factory, migrated_database_url, owner)
    _provision(authenticated_client_factory, migrated_database_url, member)

    owner_bundle = authenticated_client_factory(
        identity=owner, database_url=migrated_database_url, redis_url=None
    )
    with owner_bundle.client as client:
        create = client.post(
            "/api/v1/organisations", json={"name": "Delete Org", "slug": "delete-org"}
        )
        organisation_id = create.json()["id"]

    async def _insert_and_get_id() -> UUID:
        async with migrated_session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.external_auth_id == "kc-del-member")
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

    membership_id = run_async(_insert_and_get_id())

    with owner_bundle.client as client:
        response = client.delete(
            f"/api/v1/organisations/{organisation_id}/memberships/{membership_id}"
        )
        assert response.status_code == 204
        assert response.content == b""

    async def _get_membership() -> Membership:
        async with migrated_session_factory() as session:
            return (
                await session.execute(
                    select(Membership).where(Membership.id == membership_id)
                )
            ).scalar_one()

    assert run_async(_get_membership()).is_active is False
