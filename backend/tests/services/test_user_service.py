from __future__ import annotations

from unittest.mock import AsyncMock

from sqlalchemy.exc import IntegrityError

from app.core.auth import AuthenticatedIdentity
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async


class _DummyUser:
    def __init__(self) -> None:
        self.id = "user-id"
        self.email = "owner@example.com"
        self.email_verified = True
        self.first_name = "Owner"
        self.last_name = "User"
        self.onboarding_completed = False


async def _run_get_or_create_recovers_from_unique_conflict() -> None:
    identity = AuthenticatedIdentity(
        sub="kc-user-1",
        email="owner@example.com",
        email_verified=True,
        first_name="Owner",
        last_name="User",
    )
    user = _DummyUser()

    service = UserService(session=AsyncMock())
    service.user_repository.get_by_external_auth_id = AsyncMock(
        side_effect=[None, user]
    )
    service.user_repository.create = AsyncMock(
        side_effect=IntegrityError("insert", params=None, orig=None)
    )
    service.user_repository.update_profile_fields = AsyncMock()

    result = await service.get_or_create_current_user(identity)

    assert result is user
    assert service.user_repository.get_by_external_auth_id.await_count == 2
    service.user_repository.update_profile_fields.assert_not_called()


async def _run_get_or_create_does_not_update_when_claims_unchanged() -> None:
    identity = AuthenticatedIdentity(
        sub="kc-user-1",
        email="owner@example.com",
        email_verified=True,
        first_name="Owner",
        last_name="User",
    )
    user = _DummyUser()

    service = UserService(session=AsyncMock())
    service.user_repository.get_by_external_auth_id = AsyncMock(return_value=user)
    service.user_repository.update_profile_fields = AsyncMock()

    result = await service.get_or_create_current_user(identity)

    assert result is user
    service.user_repository.update_profile_fields.assert_not_awaited()


def test_get_or_create_recovers_from_unique_conflict() -> None:
    run_async(_run_get_or_create_recovers_from_unique_conflict())


def test_get_or_create_does_not_update_when_claims_unchanged() -> None:
    run_async(_run_get_or_create_does_not_update_when_claims_unchanged())
