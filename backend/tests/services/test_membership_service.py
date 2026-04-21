from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.errors.exceptions import ConflictError, ForbiddenError
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.services.memberships import MembershipService
from tests.helpers.asyncio_runner import run_async


def test_ensure_user_can_create_organisation_rejects_existing_membership() -> None:
    service = MembershipService(session=AsyncMock())
    service.membership_repository = AsyncMock()
    service.membership_repository.has_any_membership_for_user = AsyncMock(
        return_value=True
    )

    with pytest.raises(ConflictError):
        run_async(service.ensure_user_can_create_organisation(user_id=uuid4()))


def test_create_membership_rejects_user_with_existing_membership() -> None:
    service = MembershipService(session=AsyncMock())
    service.membership_repository = AsyncMock()
    service.membership_repository.get_membership_for_user = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
        )
    )

    with pytest.raises(ConflictError, match="User already belongs to an organisation"):
        run_async(
            service.create_membership(
                user_id=uuid4(),
                organisation_id=uuid4(),
                role=MembershipRole.MEMBER,
            )
        )


def test_ensure_user_can_list_organisation_memberships_allows_owner_and_admin() -> None:
    service = MembershipService(session=AsyncMock())
    service.membership_repository = AsyncMock()

    for role in (MembershipRole.OWNER, MembershipRole.ADMIN):
        service.membership_repository.get_membership = AsyncMock(
            return_value=Membership(
                user_id=uuid4(),
                organisation_id=uuid4(),
                role=role,
            )
        )
        run_async(
            service.ensure_user_can_list_organisation_memberships(
                user_id=uuid4(),
                organisation_id=uuid4(),
            )
        )


def test_ensure_user_can_list_organisation_memberships_forbids_member_and_non_member() -> (
    None
):
    service = MembershipService(session=AsyncMock())
    service.membership_repository = AsyncMock()

    service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
        )
    )
    with pytest.raises(ForbiddenError):
        run_async(
            service.ensure_user_can_list_organisation_memberships(
                user_id=uuid4(),
                organisation_id=uuid4(),
            )
        )

    service.membership_repository.get_membership = AsyncMock(return_value=None)
    with pytest.raises(ForbiddenError):
        run_async(
            service.ensure_user_can_list_organisation_memberships(
                user_id=uuid4(),
                organisation_id=uuid4(),
            )
        )
