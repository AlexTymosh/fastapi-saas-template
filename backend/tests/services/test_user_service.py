from __future__ import annotations

from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.auth import AuthenticatedIdentity
from app.core.db import Base
from app.users.models.user import User
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async


def _identity_for(
    *,
    sub: str = "kc-user-1",
    email: str | None = "owner@example.com",
    email_verified: bool = True,
    first_name: str | None = "Owner",
    last_name: str | None = "User",
) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        sub=sub,
        email=email,
        email_verified=email_verified,
        first_name=first_name,
        last_name=last_name,
    )


def _create_session_factory(
    tmp_path: Path,
) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/users.db")
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async def _init_models() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    run_async(_init_models())
    return session_factory, engine


def _dispose_engine(engine: AsyncEngine) -> None:
    run_async(engine.dispose())


def test_get_or_create_current_user_recovers_from_unique_conflict_race(
    tmp_path,
) -> None:
    session_factory, engine = _create_session_factory(tmp_path)

    async def _scenario() -> User:
        async with session_factory() as setup_session:
            existing_user = User(
                external_auth_id="kc-race-user",
                email="race@example.com",
                email_verified=True,
                first_name="Race",
                last_name="Condition",
            )
            setup_session.add(existing_user)
            await setup_session.commit()

        async with session_factory() as session:
            service = UserService(session=session)
            original_get = service.user_repository.get_by_external_auth_id
            read_attempts = {"count": 0}

            async def _racey_get(external_auth_id: str) -> User | None:
                read_attempts["count"] += 1
                if read_attempts["count"] == 1:
                    return None
                return await original_get(external_auth_id)

            service.user_repository.get_by_external_auth_id = _racey_get

            return await service.provision_current_user(
                _identity_for(
                    sub="kc-race-user",
                    email="race@example.com",
                    email_verified=True,
                    first_name="Race",
                    last_name="Condition",
                )
            )

    recovered_user = run_async(_scenario())
    assert recovered_user.external_auth_id == "kc-race-user"

    async def _assert_session_usable() -> int:
        async with session_factory() as session:
            result = await session.execute(select(func.count(User.id)))
            return result.scalar_one()

    assert run_async(_assert_session_usable()) == 1
    _dispose_engine(engine)


def test_provision_current_user_updates_existing_row_when_email_changes(
    tmp_path,
) -> None:
    session_factory, engine = _create_session_factory(tmp_path)

    async def _scenario() -> tuple[str, int]:
        async with session_factory() as session:
            service = UserService(session=session)
            await service.provision_current_user(
                identity=_identity_for(email="owner@example.com")
            )

        async with session_factory() as session:
            service = UserService(session=session)
            updated_user = await service.provision_current_user(
                identity=_identity_for(email="owner+new@example.com")
            )

        async with session_factory() as session:
            count_result = await session.execute(select(func.count(User.id)))
            user_count = count_result.scalar_one()

        return str(updated_user.id), user_count

    user_id, user_count = run_async(_scenario())
    assert user_count == 1

    async def _fetch_user() -> User:
        async with session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    persisted_user = run_async(_fetch_user())
    assert str(persisted_user.id) == user_id
    assert persisted_user.email == "owner+new@example.com"

    _dispose_engine(engine)


def test_provision_current_user_updates_email_verified_for_same_sub(tmp_path) -> None:
    session_factory, engine = _create_session_factory(tmp_path)

    async def _scenario() -> User:
        async with session_factory() as session:
            service = UserService(session=session)
            await service.provision_current_user(
                identity=_identity_for(email_verified=False),
            )

        async with session_factory() as session:
            service = UserService(session=session)
            await service.provision_current_user(
                identity=_identity_for(email_verified=True),
            )

        async with session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    persisted_user = run_async(_scenario())
    assert persisted_user.email_verified is True

    _dispose_engine(engine)


def test_provision_current_user_keeps_updated_at_when_claims_unchanged(
    tmp_path,
) -> None:
    session_factory, engine = _create_session_factory(tmp_path)

    async def _scenario() -> tuple[str, str, object, object]:
        async with session_factory() as session:
            service = UserService(session=session)
            first_user = await service.provision_current_user(identity=_identity_for())

        async with session_factory() as session:
            service = UserService(session=session)
            second_user = await service.provision_current_user(identity=_identity_for())

        return (
            str(first_user.id),
            str(second_user.id),
            first_user.updated_at,
            second_user.updated_at,
        )

    first_id, second_id, first_updated_at, second_updated_at = run_async(_scenario())
    assert first_id == second_id
    assert second_updated_at == first_updated_at

    _dispose_engine(engine)


def test_provision_current_user_updates_name_fields_for_same_sub(tmp_path) -> None:
    session_factory, engine = _create_session_factory(tmp_path)

    async def _scenario() -> User:
        async with session_factory() as session:
            service = UserService(session=session)
            await service.provision_current_user(
                identity=_identity_for(first_name="First", last_name="Name"),
            )

        async with session_factory() as session:
            service = UserService(session=session)
            await service.provision_current_user(
                identity=_identity_for(first_name="Updated", last_name="Person"),
            )

        async with session_factory() as session:
            result = await session.execute(select(User))
            return result.scalar_one()

    persisted_user = run_async(_scenario())
    assert persisted_user.first_name == "Updated"
    assert persisted_user.last_name == "Person"

    _dispose_engine(engine)


def test_provision_current_user_reuses_persisted_user_across_sessions(tmp_path) -> None:
    session_factory, engine = _create_session_factory(tmp_path)

    async def _scenario() -> tuple[str, str]:
        async with session_factory() as session:
            service = UserService(session=session)
            first_user = await service.provision_current_user(identity=_identity_for())

        async with session_factory() as session:
            service = UserService(session=session)
            second_user = await service.provision_current_user(identity=_identity_for())

        return str(first_user.id), str(second_user.id)

    first_id, second_id = run_async(_scenario())
    assert first_id == second_id

    _dispose_engine(engine)
