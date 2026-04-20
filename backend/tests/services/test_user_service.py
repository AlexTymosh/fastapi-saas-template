from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.core.auth.dependencies import AuthenticatedIdentity
from app.users.services.user_service import UserService
from tests.helpers.asyncio_runner import run_async


@dataclass
class FakeUser:
    id: object
    external_auth_id: str
    email: str | None
    email_verified: bool
    first_name: str | None
    last_name: str | None
    onboarding_completed: bool = False


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, FakeUser] = {}
        self.create_calls = 0
        self.update_calls = 0

    async def get_by_external_auth_id(self, external_auth_id: str) -> FakeUser | None:
        return self.users.get(external_auth_id)

    async def create(
        self,
        *,
        external_auth_id: str,
        email: str | None,
        email_verified: bool,
        first_name: str | None,
        last_name: str | None,
    ) -> FakeUser:
        self.create_calls += 1
        user = FakeUser(
            id=uuid4(),
            external_auth_id=external_auth_id,
            email=email,
            email_verified=email_verified,
            first_name=first_name,
            last_name=last_name,
        )
        self.users[external_auth_id] = user
        return user

    async def update_profile_fields(self, user: FakeUser, **kwargs) -> FakeUser:
        self.update_calls += 1
        for key, value in kwargs.items():
            if value is not None or key == "email":
                setattr(user, key, value)
        return user


class FakeMembershipRepository:
    async def user_has_any_organisation(self, _user_id: object) -> bool:
        return False


def test_get_or_create_current_user_creates_user_by_sub() -> None:
    user_repo = FakeUserRepository()
    service = UserService(
        user_repository=user_repo,
        membership_repository=FakeMembershipRepository(),
    )
    identity = AuthenticatedIdentity(
        sub="sub-123",
        email="user@example.com",
        email_verified=True,
        given_name="Alex",
        family_name="Smith",
    )

    created = run_async(service.get_or_create_current_user(identity))

    assert created.external_auth_id == "sub-123"
    assert created.email == "user@example.com"
    assert user_repo.create_calls == 1


def test_repeated_get_or_create_does_not_create_duplicate_users() -> None:
    user_repo = FakeUserRepository()
    service = UserService(
        user_repository=user_repo,
        membership_repository=FakeMembershipRepository(),
    )
    identity = AuthenticatedIdentity(sub="sub-123")

    run_async(service.get_or_create_current_user(identity))
    run_async(service.get_or_create_current_user(identity))

    assert user_repo.create_calls == 1
    assert len(user_repo.users) == 1


def test_get_or_create_current_user_minimises_updates_when_claims_unchanged() -> None:
    user_repo = FakeUserRepository()
    identity = AuthenticatedIdentity(
        sub="sub-123",
        email="user@example.com",
        email_verified=True,
        given_name="Alex",
        family_name="Smith",
    )
    run_async(
        user_repo.create(
            external_auth_id=identity.sub,
            email=identity.email,
            email_verified=identity.email_verified,
            first_name=identity.given_name,
            last_name=identity.family_name,
        )
    )

    service = UserService(
        user_repository=user_repo,
        membership_repository=FakeMembershipRepository(),
    )
    run_async(service.get_or_create_current_user(identity))

    assert user_repo.update_calls == 0
