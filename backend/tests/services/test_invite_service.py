from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
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
from app.outbox.models.outbox_event import OutboxEventType
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
    service = InviteService(session=session)
    service.outbox_service = AsyncMock()
    service.outbox_service.publish_event = AsyncMock()
    return service


def _identity(email: str = "user@example.com") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="kc-1",
        email=email,
        email_verified=True,
    )


def test_accept_invite_rejects_email_mismatch() -> None:
    service = _service()
    service.invite_repository = AsyncMock()
    service.invite_repository.accept_pending_invite_by_token_hash = AsyncMock(
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
    service.invite_repository.accept_pending_invite_by_token_hash = AsyncMock(
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
    service.membership_service.create_membership = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
        )
    )
    service.invite_repository.mark_pending_invite_expired_by_token_hash = AsyncMock(
        return_value=None
    )

    run_async(
        service.accept_invite(
            token="abc",
            identity=_identity("invited@example.com"),
        )
    )

    service.user_service.get_or_create_current_user.assert_awaited_once()


def test_user_with_active_membership_cannot_accept_invite_to_another_organisation() -> (
    None
):
    service = _service()
    invite_organisation_id = uuid4()
    user_id = uuid4()

    service.invite_repository = AsyncMock()
    invite = Invite(
        email="invited@example.com",
        organisation_id=invite_organisation_id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="x",
    )
    service.invite_repository.accept_pending_invite_by_token_hash = AsyncMock(
        return_value=invite
    )
    service.invite_repository.mark_pending_invite_expired_by_token_hash = AsyncMock(
        return_value=None
    )

    service.user_service = AsyncMock()
    user = User(
        id=user_id,
        external_auth_id="kc-1",
        email="invited@example.com",
    )
    service.user_service.get_or_create_current_user = AsyncMock(return_value=user)
    service.user_service.ensure_user_is_active = AsyncMock()

    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Acme", slug="acme")
    )

    service.membership_service = AsyncMock()
    service.membership_service.create_membership = AsyncMock(
        side_effect=ConflictError(detail="User already belongs to an organisation")
    )
    service.membership_service.transfer_membership = AsyncMock()

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("invited@example.com"),
            )
        )

    service.membership_service.create_membership.assert_awaited_once_with(
        user_id=user_id,
        organisation_id=invite_organisation_id,
        role=MembershipRole.MEMBER,
    )
    service.membership_service.transfer_membership.assert_not_awaited()
    service.invite_repository.mark_pending_invite_expired_by_token_hash.assert_not_called()


def test_user_already_in_same_organisation_cannot_accept_invite() -> None:
    service = _service()
    organisation_id = uuid4()
    service.invite_repository = AsyncMock()
    invite = Invite(
        email="invited@example.com",
        organisation_id=organisation_id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="x",
    )
    service.invite_repository.accept_pending_invite_by_token_hash = AsyncMock(
        return_value=invite
    )
    service.invite_repository.mark_pending_invite_expired_by_token_hash = AsyncMock(
        return_value=None
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
    service.membership_service.create_membership = AsyncMock(
        side_effect=ConflictError(detail="User already belongs to an organisation")
    )

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc", identity=_identity("invited@example.com")
            )
        )

    service.membership_service.create_membership.assert_awaited_once()
    service.invite_repository.mark_pending_invite_expired_by_token_hash.assert_not_called()


def test_sole_owner_cannot_be_transferred_by_accepting_invite() -> None:
    service = _service()
    invite_organisation_id = uuid4()
    user_id = uuid4()

    service.invite_repository = AsyncMock()
    invite = Invite(
        email="owner@example.com",
        organisation_id=invite_organisation_id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="x",
    )
    service.invite_repository.accept_pending_invite_by_token_hash = AsyncMock(
        return_value=invite
    )
    service.invite_repository.mark_pending_invite_expired_by_token_hash = AsyncMock(
        return_value=None
    )

    service.user_service = AsyncMock()
    user = User(
        id=user_id,
        external_auth_id="kc-owner",
        email="owner@example.com",
    )
    service.user_service.get_or_create_current_user = AsyncMock(return_value=user)
    service.user_service.ensure_user_is_active = AsyncMock()

    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=Organisation(name="Target", slug="target")
    )

    service.membership_service = AsyncMock()
    service.membership_service.create_membership = AsyncMock(
        side_effect=ConflictError(detail="User already belongs to an organisation")
    )
    service.membership_service.transfer_membership = AsyncMock()

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("owner@example.com"),
            )
        )

    service.membership_service.create_membership.assert_awaited_once_with(
        user_id=user_id,
        organisation_id=invite_organisation_id,
        role=MembershipRole.MEMBER,
    )
    service.membership_service.transfer_membership.assert_not_awaited()
    service.invite_repository.mark_pending_invite_expired_by_token_hash.assert_not_called()


def test_accept_invite_rejects_expired_pending_invite_and_marks_expired() -> None:
    service = _service()
    service.invite_repository = AsyncMock()
    expired_invite = Invite(
        email="invited@example.com",
        organisation_id=uuid4(),
        role=MembershipRole.MEMBER,
        status=InviteStatus.EXPIRED,
        token_hash="x",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    service.invite_repository.accept_pending_invite_by_token_hash = AsyncMock(
        return_value=None
    )
    service.invite_repository.mark_pending_invite_expired_by_token_hash = AsyncMock(
        return_value=expired_invite
    )
    service.user_service = AsyncMock()
    service.user_service.ensure_user_is_active = AsyncMock()

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("invited@example.com"),
            )
        )

    service.invite_repository.mark_pending_invite_expired_by_token_hash.assert_awaited_once()
    service.user_service.get_or_create_current_user.assert_not_called()


def test_accept_invite_rejects_non_pending_expired_invite() -> None:
    service = _service()
    service.invite_repository = AsyncMock()
    service.invite_repository.accept_pending_invite_by_token_hash = AsyncMock(
        return_value=None
    )
    service.invite_repository.get_by_token_hash = AsyncMock(
        return_value=Invite(
            email="invited@example.com",
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
            status=InviteStatus.ACCEPTED,
            token_hash="x",
        )
    )
    service.invite_repository.mark_pending_invite_expired_by_token_hash = AsyncMock(
        return_value=None
    )
    service.user_service = AsyncMock()
    service.user_service.ensure_user_is_active = AsyncMock()

    with pytest.raises(ConflictError):
        run_async(
            service.accept_invite(
                token="abc",
                identity=_identity("invited@example.com"),
            )
        )

    service.invite_repository.mark_pending_invite_expired_by_token_hash.assert_awaited_once()
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
    service.invite_repository.rotate_pending_invite_token = AsyncMock(return_value=None)
    service.invite_repository.mark_pending_invite_expired_by_id = AsyncMock(
        return_value=invite
    )
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

    service.invite_repository.rotate_pending_invite_token.assert_awaited_once()
    service.invite_repository.mark_pending_invite_expired_by_id.assert_awaited_once()
    service.outbox_service.publish_event.assert_not_awaited()
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


def test_create_invite_publishes_outbox_event_without_direct_delivery() -> None:
    service = _service()
    org_id = uuid4()
    actor_user_id = uuid4()
    created_invite = Invite(
        id=uuid4(),
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
    service.token_sink.deliver = AsyncMock()

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
    service.outbox_service.publish_event.assert_awaited_once()
    kwargs = service.outbox_service.publish_event.await_args.kwargs
    assert kwargs["event_type"] == OutboxEventType.INVITE_CREATED.value
    assert kwargs["aggregate_type"] == "invite"
    assert kwargs["aggregate_id"] == created_invite.id
    payload = kwargs["payload_json"]
    assert payload["invite_id"] == str(created_invite.id)
    assert payload["organisation_id"] == str(org_id)
    assert payload["email"] == created_invite.email
    assert payload["purpose"] == "created"
    assert payload["role"] == MembershipRole.MEMBER.value
    raw_token = service.payload_crypto.decrypt_token(payload["encrypted_raw_token"])
    expected_hash = sha256(raw_token.encode("utf-8")).hexdigest()
    assert "raw_token" not in payload
    assert "encrypted_raw_token" in payload
    assert payload["encrypted_raw_token"] != raw_token

    service.invite_repository.create_invite.assert_awaited_once()
    create_kwargs = service.invite_repository.create_invite.await_args.kwargs
    assert create_kwargs["token_hash"] == expected_hash
    assert create_kwargs["email"] == "invitee@example.com"
    assert create_kwargs["organisation_id"] == org_id
    assert create_kwargs["role"] == MembershipRole.MEMBER

    service.token_sink.deliver.assert_not_called()


def test_resend_invite_updates_token_hash_and_publishes_outbox_event() -> None:
    service = _service()
    org_id = uuid4()
    actor_user_id = uuid4()
    invite = Invite(
        id=uuid4(),
        email="invitee@example.com",
        organisation_id=org_id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash="old-hash",
    )
    original_expiry = invite.expires_at
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

    async def _rotate_pending_invite_token(**kwargs):
        invite.token_hash = kwargs["new_token_hash"]
        invite.expires_at = kwargs["new_expires_at"]
        return invite

    service.invite_repository.rotate_pending_invite_token = AsyncMock(
        side_effect=_rotate_pending_invite_token
    )
    service.invite_repository.mark_pending_invite_expired_by_id = AsyncMock(
        return_value=None
    )

    with patch("app.invites.services.invites.AuditEventService") as audit_service_cls:
        audit_service_cls.return_value.record_event = AsyncMock()
        resent = run_async(
            service.resend_invite(
                organisation_id=org_id,
                invite_id=uuid4(),
                actor_user_id=actor_user_id,
                audit_context=AuditContext(actor_user_id=actor_user_id),
            )
        )

    assert resent is invite
    assert invite.token_hash != "old-hash"
    assert invite.expires_at != original_expiry
    audit_service_cls.return_value.record_event.assert_awaited_once()
    service.outbox_service.publish_event.assert_awaited_once()
    kwargs = service.outbox_service.publish_event.await_args.kwargs
    assert kwargs["event_type"] == OutboxEventType.INVITE_RESEND.value
    payload = kwargs["payload_json"]
    assert payload["purpose"] == "resent"
    raw_token = service.payload_crypto.decrypt_token(payload["encrypted_raw_token"])
    assert sha256(raw_token.encode("utf-8")).hexdigest() == invite.token_hash
    assert "raw_token" not in payload
    assert payload["encrypted_raw_token"] != raw_token
    rotate_kwargs = (
        service.invite_repository.rotate_pending_invite_token.await_args.kwargs
    )
    assert rotate_kwargs["invite_id"] == invite.id
    assert rotate_kwargs["organisation_id"] == org_id
    assert rotate_kwargs["new_token_hash"] == invite.token_hash
    assert rotate_kwargs["new_expires_at"] == invite.expires_at
    assert isinstance(rotate_kwargs["now"], datetime)
