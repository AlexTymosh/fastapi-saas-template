from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.auth import AuthenticatedPrincipal
from app.organisations.models.organisation import Organisation
from app.organisations.services.access import OrganisationAccessService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


def _identity() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="kc-1",
        email="member@example.com",
        email_verified=True,
        first_name="Member",
        last_name="One",
    )


def test_get_organisation_for_member_provisions_and_checks_access() -> None:
    service = OrganisationAccessService(session=AsyncMock())

    organisation_id = uuid4()
    identity = _identity()
    user = User(
        external_auth_id=identity.external_auth_id,
        email=identity.email,
        email_verified=identity.email_verified,
        first_name=identity.first_name,
        last_name=identity.last_name,
    )
    organisation = Organisation(name="Acme", slug="acme")
    organisation.id = organisation_id

    service.user_service = AsyncMock()
    service.user_service.provision_current_user = AsyncMock(return_value=user)
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(return_value=organisation)
    service.membership_service = AsyncMock()
    service.membership_service.ensure_user_has_organisation_access = AsyncMock()

    result = run_async(
        service.get_organisation_for_member(
            identity=identity,
            organisation_id=organisation_id,
        )
    )

    assert result is organisation
    service.user_service.provision_current_user.assert_awaited_once_with(
        identity=identity
    )
    service.organisation_service.get_organisation.assert_awaited_once_with(
        organisation_id=organisation_id,
    )
    service.membership_service.ensure_user_has_organisation_access.assert_awaited_once_with(
        user_id=user.id,
        organisation_id=organisation_id,
    )


def test_service_no_longer_exposes_membership_list_method() -> None:
    service = OrganisationAccessService(session=AsyncMock())

    assert not hasattr(service, "list_memberships_for_member_organisation")
