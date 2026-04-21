from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ForbiddenError
from app.invites.models.invite import Invite, InviteStatus
from app.invites.services.invites import InviteService
from app.memberships.models.membership import MembershipRole
from tests.helpers.asyncio_runner import run_async


class _SessionStub:
    @asynccontextmanager
    async def begin(self):
        yield


def _identity(email: str = "owner@example.com") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="kc-owner",
        email=email,
        email_verified=True,
    )


def test_create_invite_rejects_owner_role() -> None:
    service = InviteService(session=AsyncMock())
    with pytest.raises(ForbiddenError):
        run_async(
            service.create_invite(
                identity=_identity(),
                organisation_id=uuid4(),
                email="a@example.com",
                role=MembershipRole.OWNER,
            )
        )


def test_accept_invite_rejects_email_mismatch() -> None:
    service = InviteService(session=_SessionStub())
    service.invite_repository = AsyncMock()
    service.invite_repository.get_by_token = AsyncMock(
        return_value=Invite(
            email="target@example.com",
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
            token="abc",
            status=InviteStatus.PENDING,
        )
    )

    with pytest.raises(ForbiddenError):
        run_async(service.accept_invite(identity=_identity("other@example.com"), token="abc"))
