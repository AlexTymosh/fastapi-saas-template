from __future__ import annotations

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.core.auth import AuthenticatedPrincipal
from app.memberships.models.membership import Membership
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


def _session_stub() -> Mock:
    session = Mock()
    session.in_transaction = Mock(return_value=False)
    session.begin = Mock()
    session.begin_nested = Mock()
    return session


def test_get_organisation_for_member_provisions_and_checks_access() -> None:
    service = OrganisationAccessService(session=_session_stub())

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
        identity=identity,
    )
    service.organisation_service.get_organisation.assert_awaited_once_with(
        organisation_id=organisation_id,
    )
    service.membership_service.ensure_user_has_organisation_access.assert_awaited_once_with(
        user_id=user.id,
        organisation_id=organisation_id,
    )


def test_list_memberships_for_member_organisation_uses_single_access_use_case() -> None:
    service = OrganisationAccessService(session=_session_stub())

    organisation_id = uuid4()
    identity = _identity()
    user = User(
        external_auth_id="kc-2",
        email="member2@example.com",
        email_verified=True,
        first_name="Member",
        last_name="Two",
    )
    memberships = [Membership(user_id=user.id, organisation_id=organisation_id)]

    service.user_service = AsyncMock()
    service.user_service.provision_current_user = AsyncMock(return_value=user)
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock()
    service.membership_service = AsyncMock()
    service.membership_service.ensure_user_can_list_organisation_memberships = (
        AsyncMock()
    )
    service.membership_service.list_memberships_for_organisation = AsyncMock(
        return_value=memberships
    )

    result = run_async(
        service.list_memberships_for_member_organisation(
            identity=identity,
            organisation_id=organisation_id,
        )
    )

    assert result == memberships
    service.user_service.provision_current_user.assert_awaited_once_with(
        identity=identity,
    )
    service.organisation_service.get_organisation.assert_awaited_once_with(
        organisation_id=organisation_id,
    )
    service.membership_service.ensure_user_can_list_organisation_memberships.assert_awaited_once_with(
        user_id=user.id,
        organisation_id=organisation_id,
    )
    service.membership_service.list_memberships_for_organisation.assert_awaited_once_with(
        organisation_id=organisation_id,
    )


def test_list_memberships_loads_organisation_before_access_check() -> None:
    service = OrganisationAccessService(session=_session_stub())

    organisation_id = uuid4()
    identity = _identity()
    user = User(
        external_auth_id="kc-sequence",
        email="sequence@example.com",
        email_verified=True,
        first_name="Sequence",
        last_name="User",
    )

    calls: list[str] = []

    service.organisation_service = AsyncMock()

    async def _load_org(*, organisation_id):
        calls.append("load_organisation")

    service.organisation_service.get_organisation = AsyncMock(side_effect=_load_org)
    service.user_service = AsyncMock()
    service.user_service.provision_current_user = AsyncMock(return_value=user)
    service.membership_service = AsyncMock()

    async def _check_access(*, user_id, organisation_id):
        calls.append("check_access")

    service.membership_service.ensure_user_can_list_organisation_memberships = (
        AsyncMock(side_effect=_check_access)
    )
    service.membership_service.list_memberships_for_organisation = AsyncMock(
        return_value=[]
    )

    run_async(
        service.list_memberships_for_member_organisation(
            identity=identity,
            organisation_id=organisation_id,
        )
    )

    assert calls == ["load_organisation", "check_access"]
