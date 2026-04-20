from __future__ import annotations

from unittest.mock import AsyncMock

from sqlalchemy.exc import IntegrityError

from app.core.auth import AuthenticatedIdentity
from app.users.models.user import User
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async


def _identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        sub="kc-race-user",
        email="race@example.com",
        email_verified=True,
        first_name="Race",
        last_name="Condition",
    )


def test_get_or_create_current_user_recovers_from_unique_conflict_race() -> None:
    service = UserService(session=AsyncMock())

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

    result = run_async(service.get_or_create_current_user(_identity()))

    assert result is existing_user
    assert repo.get_by_external_auth_id.await_count == 2
    repo.create.assert_awaited_once()
