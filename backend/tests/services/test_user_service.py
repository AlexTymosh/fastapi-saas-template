from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.core.auth import AuthenticatedIdentity
from app.users.models.user import User
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async


def _identity(
    *,
    sub: str = "kc-race-user",
    email: str = "race@example.com",
    email_verified: bool = True,
    first_name: str = "Race",
    last_name: str = "Condition",
) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        sub=sub,
        email=email,
        email_verified=email_verified,
        first_name=first_name,
        last_name=last_name,
    )


def _existing_user() -> User:
    user = User(
        external_auth_id="kc-race-user",
        email="race@example.com",
        email_verified=True,
        first_name="Race",
        last_name="Condition",
    )
    user.id = uuid4()
    user.updated_at = datetime(2026, 4, 21, 0, 0, tzinfo=timezone.utc)
    return user


def test_get_or_create_current_user_recovers_from_unique_conflict_race() -> None:
    service = UserService(session=AsyncMock())

    existing_user = _existing_user()

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


def test_get_or_create_current_user_updates_existing_row_when_email_changes() -> None:
    service = UserService(session=AsyncMock())

    existing_user = _existing_user()

    repo = AsyncMock()
    repo.get_by_external_auth_id = AsyncMock(return_value=existing_user)
    repo.update_profile_fields = AsyncMock(return_value=existing_user)
    service.user_repository = repo

    updated_identity = _identity(email="new-email@example.com")
    result = run_async(service.get_or_create_current_user(updated_identity))

    assert result is existing_user
    repo.create.assert_not_called()
    repo.update_profile_fields.assert_awaited_once_with(
        existing_user,
        email="new-email@example.com",
        email_verified=True,
        first_name="Race",
        last_name="Condition",
    )


def test_get_or_create_current_user_updates_email_verified_for_same_sub() -> None:
    service = UserService(session=AsyncMock())

    existing_user = _existing_user()
    repo = AsyncMock()
    repo.get_by_external_auth_id = AsyncMock(return_value=existing_user)
    repo.update_profile_fields = AsyncMock(return_value=existing_user)
    service.user_repository = repo

    updated_identity = _identity(email_verified=False)
    run_async(service.get_or_create_current_user(updated_identity))

    repo.update_profile_fields.assert_awaited_once_with(
        existing_user,
        email="race@example.com",
        email_verified=False,
        first_name="Race",
        last_name="Condition",
    )


def test_get_or_create_current_user_does_not_update_when_claims_unchanged() -> None:
    service = UserService(session=AsyncMock())

    existing_user = _existing_user()
    original_updated_at = existing_user.updated_at

    repo = AsyncMock()
    repo.get_by_external_auth_id = AsyncMock(return_value=existing_user)
    repo.update_profile_fields = AsyncMock()
    service.user_repository = repo

    result = run_async(service.get_or_create_current_user(_identity()))

    assert result.updated_at == original_updated_at
    repo.update_profile_fields.assert_not_awaited()
    repo.create.assert_not_called()


def test_get_or_create_current_user_updates_name_fields_for_same_sub() -> None:
    service = UserService(session=AsyncMock())

    existing_user = _existing_user()
    repo = AsyncMock()
    repo.get_by_external_auth_id = AsyncMock(return_value=existing_user)
    repo.update_profile_fields = AsyncMock(return_value=existing_user)
    service.user_repository = repo

    updated_identity = _identity(first_name="Updated", last_name="Name")
    run_async(service.get_or_create_current_user(updated_identity))

    repo.update_profile_fields.assert_awaited_once_with(
        existing_user,
        email="race@example.com",
        email_verified=True,
        first_name="Updated",
        last_name="Name",
    )
