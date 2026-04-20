from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.db import Base, get_db_session
from app.main import create_app
from app.memberships.models.membership import MembershipRole
from tests.helpers.asyncio_runner import run_async


def _identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        sub="kc-user-1",
        email="owner@example.com",
        email_verified=True,
        first_name="Owner",
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
        from sqlalchemy import select

        from app.users.models.user import User

        async with session_factory() as session:
            result = await session.execute(select(User))
            return len(result.scalars().all())

    assert run_async(_count_users()) == 1
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
