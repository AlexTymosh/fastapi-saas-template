from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.auth import AuthenticatedPrincipal
from app.core.db import Base
from app.users.models.user import User
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async


def _identity_for(
    *,
    external_auth_id: str = "kc-user-1",
    email: str | None = "owner@example.com",
    email_verified: bool = True,
    first_name: str | None = "Owner",
    last_name: str | None = "User",
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id=external_auth_id,
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


class _AsyncContextManager:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _session_stub() -> Mock:
    session = Mock()
    session.in_transaction = Mock(return_value=False)
    session.begin = Mock(return_value=_AsyncContextManager())
    session.begin_nested = Mock(return_value=_AsyncContextManager())
    return session


def test_get_or_create_current_user_recovers_from_unique_conflict_race() -> None:
    session = _session_stub()
    service = UserService(session=session)

    existing_user = User(
        external_auth_id="kc-race-user",
        email="race@example.com",
        email_verified=True,
        first_name="Race",
        last_name="Condition",
    )

    repo = AsyncMock()
    repo.get_by_external_auth_id = AsyncMock(side_effect=[None, existing_user])
    repo.create = AsyncMock(
        side_effect=IntegrityError("insert", params={}, orig=Exception("duplicate"))
    )

    service.user_repository = repo

    result = run_async(
        service.get_or_create_current_user(
            _identity_for(
                external_auth_id="kc-race-user",
                email="race@example.com",
                email_verified=True,
                first_name="Race",
                last_name="Condition",
            )
        )
    )

    assert result is existing_user
    assert repo.get_by_external_auth_id.await_count == 2
    repo.create.assert_awaited_once()
    session.begin_nested.assert_called_once_with()


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
