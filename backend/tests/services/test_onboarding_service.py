from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.core.auth.dependencies import AuthenticatedIdentity
from app.memberships.models.membership import MembershipRole
from app.onboarding.services.onboarding_service import OnboardingService
from tests.helpers.asyncio_runner import run_async


@dataclass
class FakeUser:
    id: object
    onboarding_completed: bool = False
    email: str | None = None
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None


@dataclass
class FakeOrganisation:
    id: object
    name: str
    slug: str


class FakeUserRepository:
    def __init__(self) -> None:
        self.update_calls = 0

    async def update_profile_fields(self, user: FakeUser, **kwargs) -> FakeUser:
        self.update_calls += 1
        for key, value in kwargs.items():
            setattr(user, key, value)
        return user


class FakeUserService:
    def __init__(self) -> None:
        self.user_repository = FakeUserRepository()
        self.user = FakeUser(id=uuid4())

    async def get_or_create_current_user(
        self, _identity: AuthenticatedIdentity
    ) -> FakeUser:
        return self.user


class FakeOrganisationService:
    async def create(self, *, name: str, slug: str) -> FakeOrganisation:
        return FakeOrganisation(id=uuid4(), name=name, slug=slug)


class FakeMembershipService:
    def __init__(self) -> None:
        self.roles: list[MembershipRole] = []

    async def create_owner_membership(
        self, *, user_id: object, organisation_id: object
    ):
        _ = (user_id, organisation_id)
        self.roles.append(MembershipRole.OWNER)
        return None


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        return False


class FakeSession:
    def begin(self) -> FakeTransaction:
        return FakeTransaction()


def test_create_organisation_for_current_user_assigns_owner_and_completes_onboarding(
) -> None:
    user_service = FakeUserService()
    membership_service = FakeMembershipService()
    onboarding_service = OnboardingService(
        session=FakeSession(),
        user_service=user_service,
        organisation_service=FakeOrganisationService(),
        membership_service=membership_service,
    )

    organisation = run_async(
        onboarding_service.create_organisation_for_current_user(
            identity=AuthenticatedIdentity(sub="user-sub"),
            name="Acme",
            slug="acme",
        )
    )

    assert organisation.slug == "acme"
    assert membership_service.roles == [MembershipRole.OWNER]
    assert MembershipRole.ADMIN.value == "admin"
    assert user_service.user.onboarding_completed is True
    assert user_service.user_repository.update_calls == 1
