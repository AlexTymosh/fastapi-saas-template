from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError
from app.organisations.services.onboarding import OnboardingService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


class _AsyncContextManager:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def test_create_organisation_blocks_when_user_already_has_membership() -> None:
    session = AsyncMock()
    session.begin.return_value = _AsyncContextManager()

    service = OnboardingService(session=session)
    service.user_service = AsyncMock()
    service.organisation_service = AsyncMock()
    service.membership_service = AsyncMock()

    user = User(external_auth_id="kc-existing", email="existing@example.com")
    service.user_service.get_or_create_current_user = AsyncMock(return_value=user)
    service.membership_service.list_memberships_for_user = AsyncMock(
        return_value=[AsyncMock()]
    )

    identity = AuthenticatedPrincipal(
        external_auth_id="kc-existing",
        email="existing@example.com",
    )

    with pytest.raises(ConflictError):
        run_async(
            service.create_organisation_for_current_user(
                identity=identity,
                organisation_name="Acme",
                organisation_slug="acme",
            )
        )

    service.organisation_service.create_organisation.assert_not_awaited()
    service.membership_service.create_membership.assert_not_awaited()
