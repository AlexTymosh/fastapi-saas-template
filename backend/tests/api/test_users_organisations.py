from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.db import Base, get_db_session
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


def test_users_me_creates_projection_and_does_not_duplicate(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["external_auth_id"] == "kc-user-1"

        second = client.get("/api/v1/users/me")
        assert second.status_code == 200
        assert second.json()["id"] == first_payload["id"]

    async def _count_users() -> int:
        async with session_factory() as session:
            result = await session.execute(select(User))
            return len(result.scalars().all())

    assert run_async(_count_users()) == 1
    run_async(engine.dispose())


def test_users_me_does_not_update_row_when_claims_unchanged(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200

        second = client.get("/api/v1/users/me")
        assert second.status_code == 200

    assert first.json()["updated_at"] == second.json()["updated_at"]

    async def _load_user() -> User:
        async with session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    persisted_user = run_async(_load_user())
    assert str(persisted_user.id) == first.json()["id"]
    assert persisted_user.updated_at.isoformat() == first.json()["updated_at"]
    run_async(engine.dispose())


def test_users_me_persists_projection_across_sessions_and_reuses_existing(
    tmp_path,
) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as first_client:
        first_response = first_client.get("/api/v1/users/me")
        assert first_response.status_code == 200
        first_payload = first_response.json()

    async def _load_created_user() -> User:
        async with session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    created_user = run_async(_load_created_user())
    assert str(created_user.id) == first_payload["id"]
    assert created_user.external_auth_id == "kc-user-1"

    with TestClient(app) as second_client:
        second_response = second_client.get("/api/v1/users/me")
        assert second_response.status_code == 200
        second_payload = second_response.json()

    assert second_payload["id"] == first_payload["id"]
    assert second_payload["updated_at"] == first_payload["updated_at"]
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


def test_create_organisation_sets_owner_and_onboarding_completed(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Acme Ltd", "slug": "  AcMe-ORG  "},
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "acme-org"
        organisation_id = response.json()["id"]

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        payload = me.json()
        assert payload["onboarding_completed"] is True

        memberships = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert memberships.status_code == 200
        assert memberships.json()["data"][0]["role"] == MembershipRole.OWNER.value

    run_async(engine.dispose())


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
