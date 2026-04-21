from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.db import Base, get_db_session, get_session_factory
from app.main import create_app
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


def _identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        sub="kc-user-1",
        email="owner@example.com",
        email_verified=True,
        first_name="Owner",
        last_name="User",
    )


def _identity_for(
    sub: str,
    email: str,
    *,
    email_verified: bool = True,
    first_name: str = "Test",
    last_name: str = "User",
) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        sub=sub,
        email=email,
        email_verified=email_verified,
        first_name=first_name,
        last_name=last_name,
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
    app.dependency_overrides[get_db_session] = _db_override
    app.dependency_overrides[get_current_identity] = _identity

    return app, engine, session_factory


@pytest.fixture
def migrated_api_client(client_factory, migrated_database_url) -> TestClient:
    with client_factory(database_url=migrated_database_url, redis_url=None) as client:
        client.app.dependency_overrides[get_current_identity] = _identity
        yield client
        client.app.dependency_overrides.clear()


def test_users_me_persists_projection_across_request_boundaries(migrated_api_client) -> None:
    first = migrated_api_client.get("/api/v1/users/me")
    assert first.status_code == 200
    first_payload = first.json()

    session_factory = get_session_factory()

    async def _fetch_user() -> User:
        async with session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    persisted_after_first = run_async(_fetch_user())
    first_updated_at = persisted_after_first.updated_at

    second = migrated_api_client.get("/api/v1/users/me")
    assert second.status_code == 200
    second_payload = second.json()

    persisted_after_second = run_async(_fetch_user())

    assert first_payload["external_auth_id"] == "kc-user-1"
    assert second_payload["id"] == first_payload["id"]
    assert persisted_after_first.id == persisted_after_second.id
    assert persisted_after_second.external_auth_id == "kc-user-1"
    assert persisted_after_second.updated_at == first_updated_at


def test_users_me_does_not_update_row_when_claims_unchanged(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

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
    run_async(engine.dispose())


def test_users_me_updates_row_when_claims_change(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200

        app.dependency_overrides[get_current_identity] = lambda: _identity_for(
            sub="kc-user-1",
            email="owner-updated@example.com",
            first_name="OwnerUpdated",
        )

        second = client.get("/api/v1/users/me")
        assert second.status_code == 200

    assert second.json()["email"] == "owner-updated@example.com"
    assert second.json()["first_name"] == "OwnerUpdated"
    assert second.json()["updated_at"] != first.json()["updated_at"]
    run_async(engine.dispose())


def test_users_me_updates_email_verified_for_same_sub_across_requests(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200
        first_payload = first.json()

    async def _fetch_user_by_external_id(external_auth_id: str) -> User:
        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.external_auth_id == external_auth_id)
            )
            return result.scalar_one()

    persisted_after_first = run_async(_fetch_user_by_external_id("kc-user-1"))

    with TestClient(app) as client:
        app.dependency_overrides[get_current_identity] = lambda: _identity_for(
            sub="kc-user-1",
            email="owner@example.com",
            email_verified=False,
            first_name="Owner",
            last_name="User",
        )
        second = client.get("/api/v1/users/me")
        assert second.status_code == 200
        second_payload = second.json()

    persisted_after_second = run_async(_fetch_user_by_external_id("kc-user-1"))

    assert first_payload["id"] == second_payload["id"]
    assert persisted_after_first.id == persisted_after_second.id
    assert persisted_after_first.email_verified is True
    assert second_payload["email_verified"] is False
    assert persisted_after_second.email_verified is False
    assert persisted_after_second.updated_at > persisted_after_first.updated_at
    run_async(engine.dispose())


def test_create_organisation_sets_owner_and_onboarding_completed(
    migrated_api_client,
) -> None:
    response = migrated_api_client.post(
        "/api/v1/organisations",
        json={"name": "Acme Ltd", "slug": "  AcMe-ORG  "},
    )
    assert response.status_code == 201
    assert response.json()["slug"] == "acme-org"
    organisation_id = response.json()["id"]

    me = migrated_api_client.get("/api/v1/users/me")
    assert me.status_code == 200
    payload = me.json()
    assert payload["onboarding_completed"] is True

    memberships = migrated_api_client.get(
        f"/api/v1/organisations/{organisation_id}/memberships"
    )
    assert memberships.status_code == 200
    assert memberships.json()["data"][0]["role"] == MembershipRole.OWNER.value


def test_admin_and_owner_roles_exist_in_enum() -> None:
    assert MembershipRole.ADMIN.value == "admin"
    assert MembershipRole.OWNER.value == "owner"


def test_organisation_slug_conflict_returns_problem_details(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

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
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Bad slug", "slug": "Not Valid!"},
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_get_organisation_not_found_returns_problem_details(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/organisations/{uuid4()}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_get_organisation_requires_membership_when_org_exists(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        app.dependency_overrides[get_current_identity] = lambda: _identity_for(
            sub="kc-user-2",
            email="member2@example.com",
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_get_organisation_forbidden_still_provisions_current_user(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-provision"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        app.dependency_overrides[get_current_identity] = lambda: _identity_for(
            sub="kc-user-access-1",
            email="access1@example.com",
            first_name="Access",
            last_name="Denied",
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
    app, engine, _ = _create_client_and_session_factory(tmp_path)

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
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/organisations/{uuid4()}/memberships")
        assert response.status_code == 404

    run_async(engine.dispose())


def test_list_memberships_requires_membership_when_org_exists(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-2"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        app.dependency_overrides[get_current_identity] = lambda: _identity_for(
            sub="kc-user-3",
            email="member3@example.com",
        )
        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_list_memberships_forbidden_still_provisions_current_user(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Private Org", "slug": "private-org-provision-memberships"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        app.dependency_overrides[get_current_identity] = lambda: _identity_for(
            sub="kc-user-access-2",
            email="access2@example.com",
            first_name="Access",
            last_name="Denied",
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


def test_list_memberships_returns_200_for_member(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Visible Org", "slug": "visible-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    async def _membership_role() -> str:
        async with session_factory() as session:
            result = await session.execute(select(Membership))
            return result.scalar_one().role.value

    assert run_async(_membership_role()) == MembershipRole.OWNER.value
    run_async(engine.dispose())
