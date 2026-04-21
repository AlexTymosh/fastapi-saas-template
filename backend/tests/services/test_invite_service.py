from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError, ForbiddenError
from app.invites.models.invite import Invite, InviteStatus
from app.invites.services.invites import InviteService
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


def _identity(email: str = "user@example.com") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="kc-1",
        email=email,
        email_verified=True,
    )


def test_accept_invite_rejects_email_mismatch() -> None:
    service = InviteService(session=AsyncMock())
    service.invite_repository = AsyncMock()
    service.invite_repository.get_by_token_hash = AsyncMock(
        return_value=Invite(
            email="invited@example.com",
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
            status=InviteStatus.PENDING,
            token_hash="x",
        )
    )
    service.user_repository = AsyncMock()
    service.user_repository.get_by_external_auth_id = AsyncMock(
        return_value=User(external_auth_id="kc-1", email="other@example.com")
    )

    with pytest.raises(ForbiddenError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("wrong@example.com"),
            )
        )


def test_accept_invite_rejects_missing_projection_user() -> None:
    service = InviteService(session=AsyncMock())
    service.invite_repository = AsyncMock()
    service.invite_repository.get_by_token_hash = AsyncMock(
        return_value=Invite(
            email="invited@example.com",
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
            status=InviteStatus.PENDING,
            token_hash="x",
        )
    )
    service.user_repository = AsyncMock()
    service.user_repository.get_by_external_auth_id = AsyncMock(return_value=None)

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("invited@example.com"),
            )
        )


def test_create_invite_admin_cannot_assign_admin_role() -> None:
    service = InviteService(session=AsyncMock())
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock()
    service.membership_service = AsyncMock()
    service.membership_service.membership_repository = AsyncMock()
    service.membership_service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.ADMIN,
        )
    )

    with pytest.raises(ForbiddenError):
        run_async(
            service.create_invite(
                organisation_id=uuid4(),
                actor_user_id=uuid4(),
                role=MembershipRole.ADMIN,
                email="a@example.com",
                actor_is_superadmin=False,
            )
        )
