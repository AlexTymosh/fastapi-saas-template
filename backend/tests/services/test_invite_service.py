from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.audit.context import AuditContext
from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError, ForbiddenError
from app.invites.models.invite import Invite, InviteStatus
from app.invites.services.invites import InviteService
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


@asynccontextmanager
async def _transaction_context():
    yield


def _service() -> InviteService:
    session = Mock()
    session.begin = Mock(return_value=_transaction_context())
    session.in_transaction = Mock(return_value=False)
    session.flush = AsyncMock()
    return InviteService(session=session)


class _DeliveryError(Exception):
    pass


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
    service.user_service.ensure_user_is_active = AsyncMock()

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
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Acme", slug="acme")
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
    service.user_service.ensure_user_is_active = AsyncMock()

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
    service.user_service.ensure_user_is_active = AsyncMock()

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
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(
        return_value=User(external_auth_id="kc-1", email="actor@example.com")
    )
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Acme", slug="acme")
    )
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
        actor_user_id = uuid4()
        run_async(
            service.create_invite(
                organisation_id=uuid4(),
                actor_user_id=actor_user_id,
                role=MembershipRole.ADMIN,
                email="a@example.com",
                audit_context=AuditContext(actor_user_id=actor_user_id),
            )
        )


def test_create_invite_rejects_owner_role() -> None:
    service = _service()
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock()
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock()

    with pytest.raises(ForbiddenError):
        actor_user_id = uuid4()
        run_async(
            service.create_invite(
                organisation_id=uuid4(),
                actor_user_id=actor_user_id,
                role=MembershipRole.OWNER,
                email="a@example.com",
                audit_context=AuditContext(actor_user_id=actor_user_id),
            )
        )


def test_resend_invite_rejects_expired_pending_invite_and_marks_expired() -> None:
    service = _service()
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(
        return_value=User(external_auth_id="kc-1", email="owner@example.com")
    )
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Acme", slug="acme")
    )
    service.membership_service = AsyncMock()
    service.membership_service.membership_repository = AsyncMock()
    service.membership_service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.OWNER,
        )
    )
    service.invite_repository = AsyncMock()
    invite = Invite(
        email="invited@example.com",
        organisation_id=uuid4(),
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="old",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    service.invite_repository.get_invite_for_organisation = AsyncMock(
        return_value=invite
    )
    service.invite_repository.mark_status = AsyncMock()

    with pytest.raises(ConflictError, match="Invite has expired"):
        actor_user_id = uuid4()
        run_async(
            service.resend_invite(
                organisation_id=uuid4(),
                invite_id=uuid4(),
                actor_user_id=actor_user_id,
                audit_context=AuditContext(actor_user_id=actor_user_id),
            )
        )

    service.invite_repository.mark_status.assert_awaited_once_with(
        invite, InviteStatus.EXPIRED
    )
    assert invite.token_hash == "old"


def test_create_invite_translates_integrity_error_to_conflict() -> None:
    service = _service()
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(
        return_value=User(external_auth_id="kc-1", email="owner@example.com")
    )
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Acme", slug="acme")
    )
    service.membership_service = AsyncMock()
    service.membership_service.membership_repository = AsyncMock()
    service.membership_service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.OWNER,
        )
    )
    service.invite_repository = AsyncMock()
    service.invite_repository.get_pending_invite_by_email = AsyncMock(return_value=None)
    service.invite_repository.create_invite = AsyncMock(
        side_effect=IntegrityError("stmt", {}, Exception("duplicate"))
    )

    with pytest.raises(ConflictError, match="Pending invite already exists"):
        actor_user_id = uuid4()
        run_async(
            service.create_invite(
                organisation_id=uuid4(),
                actor_user_id=actor_user_id,
                role=MembershipRole.MEMBER,
                email="invitee@example.com",
                audit_context=AuditContext(actor_user_id=actor_user_id),
            )
        )


def test_create_invite_delivery_failure_does_not_raise() -> None:
    service = _service()
    org_id = uuid4()
    actor_user_id = uuid4()
    created_invite = Invite(
        email="invitee@example.com",
        organisation_id=org_id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="hash",
    )
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(return_value=object())
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Acme", slug="acme")
    )
    service.membership_service = AsyncMock()
    service.membership_service.membership_repository = AsyncMock()
    service.membership_service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=actor_user_id, organisation_id=org_id, role=MembershipRole.OWNER
        )
    )
    service.invite_repository = AsyncMock()
    service.invite_repository.get_pending_invite_by_email = AsyncMock(return_value=None)
    service.invite_repository.create_invite = AsyncMock(return_value=created_invite)
    service.token_sink = AsyncMock()
    service.token_sink.deliver = AsyncMock(side_effect=_DeliveryError("downstream"))

    with patch("app.invites.services.invites.AuditEventService") as audit_service_cls:
        audit_service_cls.return_value.record_event = AsyncMock()
        invite = run_async(
            service.create_invite(
                organisation_id=org_id,
                actor_user_id=actor_user_id,
                role=MembershipRole.MEMBER,
                email="invitee@example.com",
                audit_context=AuditContext(actor_user_id=actor_user_id),
            )
        )

    assert invite is created_invite
    audit_service_cls.return_value.record_event.assert_awaited_once()


def test_resend_invite_delivery_failure_does_not_raise() -> None:
    service = _service()
    org_id = uuid4()
    actor_user_id = uuid4()
    invite = Invite(
        email="invitee@example.com",
        organisation_id=org_id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="old-hash",
    )
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(return_value=object())
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Acme", slug="acme")
    )
    service.membership_service = AsyncMock()
    service.membership_service.membership_repository = AsyncMock()
    service.membership_service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=actor_user_id, organisation_id=org_id, role=MembershipRole.OWNER
        )
    )
    service.invite_repository = AsyncMock()
    service.invite_repository.get_invite_for_organisation = AsyncMock(
        return_value=invite
    )
    service.token_sink = AsyncMock()
    service.token_sink.deliver = AsyncMock(side_effect=_DeliveryError("downstream"))

    with patch("app.invites.services.invites.AuditEventService") as audit_service_cls:
        audit_service_cls.return_value.record_event = AsyncMock()
        result = run_async(
            service.resend_invite(
                organisation_id=org_id,
                invite_id=uuid4(),
                actor_user_id=actor_user_id,
                audit_context=AuditContext(actor_user_id=actor_user_id),
            )
        )

    assert result is invite
    assert invite.token_hash != "old-hash"
    audit_service_cls.return_value.record_event.assert_awaited_once()


def test_create_invite_rejects_external_transaction_before_delivery() -> None:
    service = _service()
    service.session.in_transaction = Mock(return_value=True)
    service.token_sink = AsyncMock()
    service.token_sink.deliver = AsyncMock()
    service.invite_repository = AsyncMock()

    actor_user_id = uuid4()
    with patch("app.invites.services.invites.AuditEventService") as audit_service_cls:
        audit_service_cls.return_value.record_event = AsyncMock()
        with pytest.raises(
            RuntimeError, match="Invite delivery requires service-owned transaction"
        ):
            run_async(
                service.create_invite(
                    organisation_id=uuid4(),
                    actor_user_id=actor_user_id,
                    role=MembershipRole.MEMBER,
                    email="invitee@example.com",
                    audit_context=AuditContext(actor_user_id=actor_user_id),
                )
            )

    service.session.begin.assert_not_called()
    service.invite_repository.create_invite.assert_not_called()
    service.token_sink.deliver.assert_not_called()
    audit_service_cls.return_value.record_event.assert_not_called()


def test_resend_invite_rejects_external_transaction_before_delivery() -> None:
    service = _service()
    service.session.in_transaction = Mock(return_value=True)
    service.token_sink = AsyncMock()
    service.token_sink.deliver = AsyncMock()
    service.invite_repository = AsyncMock()

    actor_user_id = uuid4()
    with patch("app.invites.services.invites.AuditEventService") as audit_service_cls:
        audit_service_cls.return_value.record_event = AsyncMock()
        with pytest.raises(
            RuntimeError, match="Invite delivery requires service-owned transaction"
        ):
            run_async(
                service.resend_invite(
                    organisation_id=uuid4(),
                    invite_id=uuid4(),
                    actor_user_id=actor_user_id,
                    audit_context=AuditContext(actor_user_id=actor_user_id),
                )
            )

    service.session.begin.assert_not_called()
    service.invite_repository.get_invite_for_organisation.assert_not_called()
    service.token_sink.deliver.assert_not_called()
    audit_service_cls.return_value.record_event.assert_not_called()
