from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.db import Base, get_db_session
from app.main import create_app
from app.memberships.models.membership import MembershipRole
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


def _identity_for(sub: str, email: str) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        sub=sub,
        email=email,
        email_verified=True,
        first_name="Test",
        last_name="User",
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


def test_user_upsert_by_sub_and_no_duplicates(tmp_path) -> None:
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
            result = await session.execute(select(func.count(User.id)))
            return int(result.scalar_one())

    assert run_async(_count_users()) == 1
    run_async(engine.dispose())


def test_user_me_does_not_update_when_claims_unchanged(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200

    async def _user_timestamps() -> tuple[str, str]:
        async with session_factory() as session:
            result = await session.execute(select(User))
            user = result.scalar_one()
            return (user.created_at.isoformat(), user.updated_at.isoformat())

    before = run_async(_user_timestamps())

    with TestClient(app) as client:
        second = client.get("/api/v1/users/me")
        assert second.status_code == 200

    after = run_async(_user_timestamps())
    assert before == after
    run_async(engine.dispose())


def test_user_me_updates_when_claims_change(tmp_path) -> None:
    app, engine, session_factory = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        first = client.get("/api/v1/users/me")
        assert first.status_code == 200

    app.dependency_overrides[get_current_identity] = lambda: AuthenticatedIdentity(
        sub="kc-user-1",
        email="owner-updated@example.com",
        email_verified=True,
        first_name="Owner",
        last_name="Renamed",
    )

    with TestClient(app) as client:
        second = client.get("/api/v1/users/me")
        assert second.status_code == 200
        payload = second.json()
        assert payload["email"] == "owner-updated@example.com"
        assert payload["last_name"] == "Renamed"

    async def _read_user() -> User:
        async with session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    user = run_async(_read_user())
    assert user.email == "owner-updated@example.com"
    assert user.last_name == "Renamed"
    run_async(engine.dispose())


def test_create_organisation_sets_owner_and_onboarding_completed(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Acme Ltd", "slug": "acme"},
        )
        assert response.status_code == 201
        organisation_id = response.json()["id"]

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        payload = me.json()
        assert payload["onboarding_completed"] is True

        memberships = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert memberships.status_code == 200
        assert memberships.json()["data"][0]["role"] == MembershipRole.OWNER.value

    run_async(engine.dispose())


def test_admin_role_exists_in_enum() -> None:
    assert MembershipRole.ADMIN.value == "admin"
    assert MembershipRole.OWNER.value == "owner"


def test_organisation_slug_normalizes_on_create(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Acme Ltd", "slug": "  Mixed-CASE-42  "},
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "mixed-case-42"

    run_async(engine.dispose())


def test_organisation_slug_rejects_invalid_symbols(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organisations",
            json={"name": "Acme Ltd", "slug": "acme corp"},
        )
        assert response.status_code == 422

    run_async(engine.dispose())


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
            json={"name": "Second", "slug": "taken"},
        )
        assert second.status_code == 409
        assert second.headers["content-type"].startswith("application/problem+json")
        assert second.json()["error_code"] == "conflict"

    run_async(engine.dispose())


def test_get_organisation_not_found_returns_problem_details(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/organisations/{uuid4()}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")

    run_async(engine.dispose())


def test_get_organisation_requires_membership(tmp_path) -> None:
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


def test_get_organisation_returns_200_for_members(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Visible Org", "slug": "visible-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        response = client.get(f"/api/v1/organisations/{organisation_id}")
        assert response.status_code == 200
        assert response.json()["id"] == organisation_id

    run_async(engine.dispose())


def test_list_memberships_not_found_returns_404(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/organisations/{uuid4()}/memberships")
        assert response.status_code == 404

    run_async(engine.dispose())


def test_list_memberships_requires_membership(tmp_path) -> None:
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


def test_list_memberships_returns_200_for_members(tmp_path) -> None:
    app, engine, _ = _create_client_and_session_factory(tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/organisations",
            json={"name": "Members Org", "slug": "members-org"},
        )
        assert create_response.status_code == 201
        organisation_id = create_response.json()["id"]

        response = client.get(f"/api/v1/organisations/{organisation_id}/memberships")
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    run_async(engine.dispose())
