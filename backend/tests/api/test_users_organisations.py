from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.db import Base, get_db_session
from app.main import create_app
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import FakeAuthProvider


def _identity() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="kc-user-1",
        email="owner@example.com",
        email_verified=True,
        first_name="Owner",
        last_name="User",
    )


def _identity_for(
    external_auth_id: str,
    email: str,
    *,
    roles: list[str] | None = None,
    email_verified: bool = True,
    first_name: str = "Test",
    last_name: str = "User",
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id=external_auth_id,
        email=email,
        email_verified=email_verified,
        first_name=first_name,
        last_name=last_name,
        platform_roles=roles or [],
    )


def _create_client_and_session_factory(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path}/app.db"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async def _init_models() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    run_async(_init_models())

    async def _db_override():
        async with session_factory() as session:
            yield session

    app = create_app()
    auth_provider = FakeAuthProvider(identity=_identity())
    app.dependency_overrides[get_db_session] = _db_override
    app.dependency_overrides[get_authenticated_principal] = (
        auth_provider.get_authenticated_principal
    )

    return app, engine, session_factory, auth_provider


def test_protected_endpoints_return_401_without_auth(client_factory) -> None:
    with client_factory(database_url=None, redis_url=None) as client:
        endpoints = [
            ("get", "/api/v1/users/me"),
            ("post", "/api/v1/organisations"),
            ("get", f"/api/v1/organisations/{uuid4()}"),
            ("get", f"/api/v1/organisations/{uuid4()}/memberships"),
        ]
        for method, path in endpoints:
            if method == "post":
                response = client.post(
                    path,
                    json={"name": "Unauth Org", "slug": "unauth-org"},
                )
            else:
                response = getattr(client, method)(path)
            assert response.status_code == 401
            assert response.headers["content-type"].startswith(
                "application/problem+json"
            )


def test_authenticated_client_uses_explicit_test_auth_provider(
    authenticated_client_factory, migrated_database_url: str
) -> None:
    test_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            external_auth_id="kc-explicit-auth-user",
            email="explicit@example.com",
            first_name="Explicit",
            last_name="Identity",
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    test_client = test_client_bundle.client
    with test_client as client:
        response = client.get("/api/v1/users/me")
        assert response.status_code == 200
        assert response.json()["external_auth_id"] == "kc-explicit-auth-user"


def test_users_me_persists_projection_across_request_boundaries(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    test_client_bundle = authenticated_client_factory(
        identity=_identity(),
        database_url=migrated_database_url,
        redis_url=None,
    )
    test_client = test_client_bundle.client
    with test_client as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200
        first_payload = first.json()

    async def _fetch_user() -> User:
        async with migrated_session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    persisted_after_first = run_async(_fetch_user())
    first_updated_at = persisted_after_first.updated_at

    test_client_bundle = authenticated_client_factory(
        identity=_identity(),
        database_url=migrated_database_url,
        redis_url=None,
    )
    test_client = test_client_bundle.client
    with test_client as client:
        second = client.get("/api/v1/users/me")
        assert second.status_code == 200
        second_payload = second.json()

    persisted_after_second = run_async(_fetch_user())

    assert first_payload["external_auth_id"] == "kc-user-1"
    assert second_payload["id"] == first_payload["id"]
    assert persisted_after_first.id == persisted_after_second.id
    assert persisted_after_second.external_auth_id == "kc-user-1"
    assert persisted_after_second.updated_at == first_updated_at


def test_users_me_does_not_update_row_when_claims_unchanged(tmp_path) -> None:
    app, engine, session_factory, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200

        second = client.get("/api/v1/users/me")
        assert second.status_code == 200

    async def _updated_at() -> datetime:
        async with session_factory() as session:
            result = await session.execute(select(User.updated_at))
            return result.scalar_one()

    persisted_updated_at = run_async(_updated_at())

    assert first.json()["updated_at"] == second.json()["updated_at"]
    assert persisted_updated_at.isoformat() == first.json()["updated_at"]
    assert first.json()["membership"] is None
    assert second.json()["membership"] is None
    run_async(engine.dispose())


def test_users_me_updates_row_when_claims_change(tmp_path) -> None:
    app, engine, _, auth_provider = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-user-1",
                email="owner-updated@example.com",
                first_name="OwnerUpdated",
            )
        )

        second = client.get("/api/v1/users/me")
        assert second.status_code == 200

    assert second.json()["email"] == "owner-updated@example.com"
    assert second.json()["first_name"] == "OwnerUpdated"
    assert second.json()["updated_at"] != first.json()["updated_at"]
    run_async(engine.dispose())


def test_users_me_updates_email_verified_for_same_sub_across_requests(tmp_path) -> None:
    app, engine, session_factory, auth_provider = _create_client_and_session_factory(
        tmp_path
    )

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200
        first_payload = first.json()

    async def _fetch_user_by_external_auth_id(external_auth_id: str) -> User:
        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.external_auth_id == external_auth_id)
            )
            return result.scalar_one()

    persisted_after_first = run_async(_fetch_user_by_external_auth_id("kc-user-1"))

    with TestClient(app) as client:
        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-user-1",
                email="owner@example.com",
                email_verified=False,
                first_name="Owner",
                last_name="User",
            )
        )
        second = client.get("/api/v1/users/me")
        assert second.status_code == 200
        second_payload = second.json()

    persisted_after_second = run_async(_fetch_user_by_external_auth_id("kc-user-1"))

    assert first_payload["id"] == second_payload["id"]
    assert persisted_after_first.id == persisted_after_second.id
    assert persisted_after_first.email_verified is True
    assert second_payload["email_verified"] is False
    assert persisted_after_second.email_verified is False
    assert persisted_after_second.updated_at > persisted_after_first.updated_at
    run_async(engine.dispose())


def test_create_organisation_sets_owner_and_onboarding_completed(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    test_client_bundle = authenticated_client_factory(
        identity=_identity(),
        database_url=migrated_database_url,
        redis_url=None,
    )
    test_client = test_client_bundle.client
    with test_client as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Acme Ltd", "slug": "  AcMe-ORG  "},
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "acme-org"
        assert response.json()["status"] == OrganisationStatus.ACTIVE.value
        organisation_id = response.json()["id"]

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        payload = me.json()
        assert payload["onboarding_completed"] is True
        assert payload["status"] == UserStatus.ACTIVE.value
        assert payload["membership"]["organisation_id"] == organisation_id
        assert payload["membership"]["role"] == MembershipRole.OWNER.value

        memberships_response = client.get(
            f"/api/v1/organisations/{organisation_id}/memberships"
        )
        assert memberships_response.status_code == 200
        memberships_payload = memberships_response.json()
        assert "data" in memberships_payload
        assert "meta" in memberships_payload
        assert "links" in memberships_payload
        assert memberships_payload["meta"]["total"] == len(memberships_payload["data"])
        assert memberships_payload["data"][0]["role"] == MembershipRole.OWNER.value


def test_admin_and_owner_roles_exist_in_enum() -> None:
    assert MembershipRole.ADMIN.value == "admin"
    assert MembershipRole.OWNER.value == "owner"


def test_unverified_email_cannot_create_organisation(tmp_path) -> None:
    app, engine, _, auth_provider = _create_client_and_session_factory(tmp_path)

    auth_provider.set_identity(
        _identity_for(
            external_auth_id="kc-unverified",
            email="unverified@example.com",
            email_verified=False,
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Blocked Org", "slug": "blocked-unverified"},
        )
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_organisation_slug_conflict_returns_problem_details(tmp_path) -> None:
    app, engine, _, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/organisations",
            json={"name": "First", "slug": "taken"},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/v1/organisations",
            json={"name": "Second", "slug": "  TAKEN "},
        )
        assert second.status_code == 409
        assert second.headers["content-type"].startswith("application/problem+json")
        assert second.json()["error_code"] == "conflict"

    run_async(engine.dispose())


def test_create_organisation_invalid_slug_returns_validation_problem(tmp_path) -> None:
    app, engine, _, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Bad slug", "slug": "Not Valid!"},
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_get_organisation_not_found_returns_problem_details(tmp_path) -> None:
    app, engine, _, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/organisations/{uuid4()}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_get_organisation_requires_membership_when_org_exists(tmp_path) -> None:
    app, engine, _, auth_provider = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-user-2",
                email="member2@example.com",
            )
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_get_organisation_forbidden_still_provisions_current_user(tmp_path) -> None:
    app, engine, session_factory, auth_provider = _create_client_and_session_factory(
        tmp_path
    )

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-provision"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-user-access-1",
                email="access1@example.com",
                first_name="Access",
                last_name="Denied",
            )
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert response.status_code == 403

    async def _fetch_user() -> User:
        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.external_auth_id == "kc-user-access-1")
            )
            return result.scalar_one()

    user = run_async(_fetch_user())
    assert user.external_auth_id == "kc-user-access-1"
    assert user.email == "access1@example.com"
    assert user.first_name == "Access"
    assert user.last_name == "Denied"
    run_async(engine.dispose())


def test_get_organisation_returns_200_for_member(tmp_path) -> None:
    app, engine, _, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Member Org", "slug": "member-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert response.status_code == 200

    run_async(engine.dispose())


def test_list_memberships_not_found_returns_404(tmp_path) -> None:
    app, engine, _, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/organisations/{uuid4()}/memberships")
        assert response.status_code == 404

    run_async(engine.dispose())


def test_list_memberships_requires_membership_when_org_exists(tmp_path) -> None:
    app, engine, _, auth_provider = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-2"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-user-3",
                email="member3@example.com",
            )
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_list_memberships_forbidden_still_provisions_current_user(tmp_path) -> None:
    app, engine, session_factory, auth_provider = _create_client_and_session_factory(
        tmp_path
    )

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-provision-memberships"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-user-access-2",
                email="access2@example.com",
                first_name="Access",
                last_name="Denied",
            )
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 403

    async def _fetch_user() -> User:
        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.external_auth_id == "kc-user-access-2")
            )
            return result.scalar_one()

    user = run_async(_fetch_user())
    assert user.external_auth_id == "kc-user-access-2"
    assert user.email == "access2@example.com"
    assert user.first_name == "Access"
    assert user.last_name == "Denied"
    run_async(engine.dispose())


def test_list_memberships_returns_200_for_owner(tmp_path) -> None:
    app, engine, session_factory, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Visible Org", "slug": "visible-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 200
        payload = response.json()
        assert "data" in payload
        assert "meta" in payload
        assert "links" in payload
        assert payload["meta"]["total"] == len(payload["data"])
        assert len(payload["data"]) == 1

    async def _membership_role() -> str:
        async with session_factory() as session:
            result = await session.execute(select(Membership))
            return result.scalar_one().role.value

    assert run_async(_membership_role()) == MembershipRole.OWNER.value
    run_async(engine.dispose())


def test_list_memberships_returns_404_for_soft_deleted_organisation_even_for_non_member(
    tmp_path,
) -> None:
    app, engine, _, auth_provider = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Soft Deleted Org", "slug": "soft-deleted-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        delete_response = client.delete(f"/api/v1/organisations/{organisation_id}")
        assert delete_response.status_code == 204

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-soft-delete-outsider",
                email="soft-delete-outsider@example.com",
            )
        )

        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 404

    run_async(engine.dispose())


def test_create_organisation_rejects_second_creation_for_same_user(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    identity = _identity_for(
        external_auth_id="kc-single-org-user",
        email="single-org@example.com",
    )
    test_client_bundle = authenticated_client_factory(
        identity=identity,
        database_url=migrated_database_url,
        redis_url=None,
    )
    test_client = test_client_bundle.client
    with test_client as client:
        first = client.post(
            "/api/v1/organisations",
            json={"name": "First Org", "slug": "single-org-first"},
        )
        second = client.post(
            "/api/v1/organisations",
            json={"name": "Second Org", "slug": "single-org-second"},
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    assert second.json()["error_code"] == "conflict"


def test_users_me_membership_is_null_when_user_has_no_organisation(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    test_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            external_auth_id="kc-no-org-user",
            email="no-org@example.com",
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    test_client = test_client_bundle.client
    with test_client as client:
        response = client.get("/api/v1/users/me")

    assert response.status_code == 200
    assert response.json()["membership"] is None


def _provision_user_via_api(
    authenticated_client_factory,
    *,
    migrated_database_url: str,
    identity: AuthenticatedPrincipal,
) -> None:
    test_client_bundle = authenticated_client_factory(
        identity=identity,
        database_url=migrated_database_url,
        redis_url=None,
    )
    test_client = test_client_bundle.client
    with test_client as client:
        response = client.get("/api/v1/users/me")
    assert response.status_code == 200


def _insert_membership_with_role(
    migrated_session_factory,
    *,
    external_auth_id: str,
    organisation_id: str,
    role: MembershipRole,
) -> None:
    async def _insert() -> None:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(User).where(User.external_auth_id == external_auth_id)
            )
            user = result.scalar_one()
            session.add(
                Membership(
                    user_id=user.id,
                    organisation_id=UUID(organisation_id),
                    role=role,
                )
            )
            await session.commit()

    run_async(_insert())


def test_list_memberships_allows_admin_but_forbids_member_and_non_member(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_identity = _identity_for(
        external_auth_id="kc-role-owner",
        email="owner-role@example.com",
    )
    owner_client_bundle = authenticated_client_factory(
        identity=owner_identity,
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    with owner_client as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Role Org", "slug": "role-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]
        owner_memberships = client.get(
            f"/api/v1/organisations/{organisation_id}/memberships"
        )
        assert owner_memberships.status_code == 200

    admin_identity = _identity_for(
        external_auth_id="kc-role-admin",
        email="admin-role@example.com",
    )
    member_identity = _identity_for(
        external_auth_id="kc-role-member",
        email="member-role@example.com",
    )
    outsider_identity = _identity_for(
        external_auth_id="kc-role-outsider",
        email="outsider-role@example.com",
    )

    _provision_user_via_api(
        authenticated_client_factory,
        migrated_database_url=migrated_database_url,
        identity=admin_identity,
    )
    _provision_user_via_api(
        authenticated_client_factory,
        migrated_database_url=migrated_database_url,
        identity=member_identity,
    )
    _provision_user_via_api(
        authenticated_client_factory,
        migrated_database_url=migrated_database_url,
        identity=outsider_identity,
    )

    _insert_membership_with_role(
        migrated_session_factory,
        external_auth_id=admin_identity.external_auth_id,
        organisation_id=organisation_id,
        role=MembershipRole.ADMIN,
    )
    _insert_membership_with_role(
        migrated_session_factory,
        external_auth_id=member_identity.external_auth_id,
        organisation_id=organisation_id,
        role=MembershipRole.MEMBER,
    )

    admin_client_bundle = authenticated_client_factory(
        identity=admin_identity,
        database_url=migrated_database_url,
        redis_url=None,
    )
    admin_client = admin_client_bundle.client
    with admin_client as client:
        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 200

    member_client_bundle = authenticated_client_factory(
        identity=member_identity,
        database_url=migrated_database_url,
        redis_url=None,
    )
    member_client = member_client_bundle.client
    with member_client as client:
        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 403

    outsider_client_bundle = authenticated_client_factory(
        identity=outsider_identity,
        database_url=migrated_database_url,
        redis_url=None,
    )
    outsider_client = outsider_client_bundle.client
    with outsider_client as client:
        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 403


def test_platform_role_does_not_grant_organisation_read_access(tmp_path) -> None:
    app, engine, _, auth_provider = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-platform-read"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-platform-actor-read",
                email="platform-read@example.com",
                roles=["platform_admin"],
            )
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_superadmin_role_claim_does_not_grant_membership_list_access(tmp_path) -> None:
    app, engine, _, auth_provider = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-super-role-list"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        auth_provider.set_identity(
            _identity_for(
                external_auth_id="kc-platform-actor-list",
                email="platform-list@example.com",
                roles=["superadmin"],
            )
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_owner_can_update_slug_and_soft_delete_organisation(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            external_auth_id="kc-owner-mutate-org",
            email="owner-mutate-org@example.com",
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    with owner_client as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Mutable Org", "slug": "mutable-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        patch_response = client.patch(
            f"/api/v1/organisations/{organisation_id}/slug",
            json={"slug": "mutable-org-updated"},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["slug"] == "mutable-org-updated"

        delete_response = client.delete(f"/api/v1/organisations/{organisation_id}")
        assert delete_response.status_code == 204

        get_response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert get_response.status_code == 404


def test_update_organisation_slug_invalid_payload_returns_validation_problem(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            external_auth_id="kc-owner-invalid-slug",
            email="owner-invalid-slug@example.com",
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    with owner_client as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Invalid Slug Org", "slug": "invalid-slug-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        patch_response = client.patch(
            f"/api/v1/organisations/{organisation_id}/slug",
            json={"slug": "Not Valid!"},
        )
        assert patch_response.status_code == 422
        assert patch_response.headers["content-type"].startswith(
            "application/problem+json"
        )


def test_soft_deleted_organisation_slug_is_released_for_reuse(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    first_owner_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            external_auth_id="kc-owner-reusable-slug-1",
            email="owner-reusable-slug-1@example.com",
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    first_owner_client = first_owner_client_bundle.client
    with first_owner_client as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Reusable Slug Org 1", "slug": "reusable-org"},
        )
        assert create_response.status_code == 201
        first_organisation_id = UUID(create_response.json()["id"])

        delete_response = client.delete(
            f"/api/v1/organisations/{first_organisation_id}"
        )
        assert delete_response.status_code == 204

    async def _fetch_soft_deleted_org(org_id: UUID) -> Organisation:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            return result.scalar_one()

    soft_deleted_org = run_async(_fetch_soft_deleted_org(first_organisation_id))
    assert soft_deleted_org.deleted_at is not None
    assert soft_deleted_org.slug != "reusable-org"
    assert soft_deleted_org.slug == f"deleted-{soft_deleted_org.id}-reusable-org"

    second_owner_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            external_auth_id="kc-owner-reusable-slug-2",
            email="owner-reusable-slug-2@example.com",
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    second_owner_client = second_owner_client_bundle.client
    with second_owner_client as client:
        recreate_response = client.post(
            "/api/v1/organisations",
            json={"name": "Reusable Slug Org 2", "slug": "reusable-org"},
        )
        assert recreate_response.status_code == 201
        assert recreate_response.json()["slug"] == "reusable-org"


def test_suspended_user_cannot_create_organisation(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    bundle = authenticated_client_factory(
        identity=_identity(), database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        me = client.get("/api/v1/users/me")
        assert me.status_code == 200

    async def _suspend() -> None:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(User).where(User.external_auth_id == "kc-user-1")
            )
            user = result.scalar_one()
            user.status = UserStatus.SUSPENDED
            await session.commit()

    run_async(_suspend())

    bundle = authenticated_client_factory(
        identity=_identity(), database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.post(
            "/api/v1/organisations", json={"name": "Suspended", "slug": "suspended-org"}
        )
        assert response.status_code == 403


def test_suspended_organisation_returns_403_for_get(
    authenticated_client_factory, migrated_database_url: str, migrated_session_factory
) -> None:
    bundle = authenticated_client_factory(
        identity=_identity(), database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        create = client.post(
            "/api/v1/organisations", json={"name": "Acme", "slug": "acme-susp"}
        )
        organisation_id = create.json()["id"]

    async def _suspend_org() -> None:
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(Organisation).where(Organisation.id == UUID(organisation_id))
            )
            organisation = result.scalar_one()
            organisation.status = OrganisationStatus.SUSPENDED
            await session.commit()

    run_async(_suspend_org())

    bundle = authenticated_client_factory(
        identity=_identity(), database_url=migrated_database_url, redis_url=None
    )
    with bundle.client as client:
        response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert response.status_code == 403
