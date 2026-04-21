from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError, ForbiddenError
from app.invites.models.invite import Invite, InviteStatus
from app.invites.services.invites import InviteService
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


@asynccontextmanager
async def _transaction_context():
    yield


def _service() -> InviteService:
    session = Mock()
    session.begin = Mock(return_value=_transaction_context())
    session.in_transaction = Mock(return_value=False)
    return InviteService(session=session)


def _identity(email: str = "user@example.com") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="kc-1",
        email=email,
        email_verified=True,
    )


def test_accept_invite_rejects_email_mismatch() -> None:
    service = _service()
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
    service.user_service = AsyncMock()

    with pytest.raises(ForbiddenError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("wrong@example.com"),
            )
        )


def test_accept_invite_provisions_missing_projection_user() -> None:
    service = _service()
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
    service.user_service = AsyncMock()
    service.user_service.get_or_create_current_user = AsyncMock(
        return_value=User(external_auth_id="kc-1", email="invited@example.com")
    )
    service.membership_service = AsyncMock()
    service.membership_service.transfer_membership = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
        )
    )
    service.invite_repository.mark_status = AsyncMock()

    run_async(
        service.accept_invite(
            token="abc",
            identity=_identity("invited@example.com"),
        )
    )

    service.user_service.get_or_create_current_user.assert_awaited_once()


def test_accept_invite_rejects_expired_pending_invite_and_marks_expired() -> None:
    service = _service()
    service.invite_repository = AsyncMock()
    invite = Invite(
        email="invited@example.com",
        organisation_id=uuid4(),
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="x",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    service.invite_repository.get_by_token_hash = AsyncMock(return_value=invite)
    service.invite_repository.mark_status = AsyncMock()
    service.user_service = AsyncMock()

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("invited@example.com"),
            )
        )

    service.invite_repository.mark_status.assert_awaited_once_with(
        invite, InviteStatus.EXPIRED
    )
    service.user_service.get_or_create_current_user.assert_not_called()


def test_accept_invite_rejects_non_pending_expired_invite() -> None:
    service = _service()
    service.invite_repository = AsyncMock()
    service.invite_repository.get_by_token_hash = AsyncMock(
        return_value=Invite(
            email="invited@example.com",
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
            status=InviteStatus.EXPIRED,
            token_hash="x",
        )
    )
    service.invite_repository.mark_status = AsyncMock()
    service.user_service = AsyncMock()

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("invited@example.com"),
            )
        )

    service.invite_repository.mark_status.assert_not_called()
    service.user_service.get_or_create_current_user.assert_not_called()


def test_create_invite_admin_cannot_assign_admin_role() -> None:
    service = _service()
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


def test_create_invite_rejects_owner_role() -> None:
    service = _service()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock()

    with pytest.raises(ForbiddenError):
        run_async(
            service.create_invite(
                organisation_id=uuid4(),
                actor_user_id=uuid4(),
                role=MembershipRole.OWNER,
                email="a@example.com",
                actor_is_superadmin=True,
            )
        )
