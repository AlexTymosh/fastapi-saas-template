from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.audit.context import AuditContext
from app.core.errors.exceptions import ConflictError, ForbiddenError
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.services.memberships import MembershipService
from tests.helpers.asyncio_runner import run_async


class _AsyncContextManager:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _session_stub() -> Mock:
    session = Mock()
    session.in_transaction = Mock(return_value=False)
    session.begin = Mock(return_value=_AsyncContextManager())
    return session


def test_ensure_user_can_create_organisation_rejects_existing_membership() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    service.membership_repository.get_membership_for_user = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
        )
    )

    with pytest.raises(ConflictError):
        run_async(service.ensure_user_can_create_organisation(user_id=uuid4()))


def test_create_membership_rejects_user_with_existing_membership() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    service.membership_repository.get_membership_for_user = AsyncMock(
        return_value=Membership(
            user_id=uuid4(),
            organisation_id=uuid4(),
            role=MembershipRole.MEMBER,
        )
    )

    with pytest.raises(ConflictError, match="already belongs to an organisation"):
        run_async(
            service.create_membership(
                user_id=uuid4(),
                organisation_id=uuid4(),
                role=MembershipRole.MEMBER,
            )
        )


def test_create_membership_maps_integrity_error_to_policy_conflict() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    service.membership_repository.get_membership_for_user = AsyncMock(return_value=None)
    service.membership_repository.create_membership = AsyncMock(
        side_effect=IntegrityError("insert", params={}, orig=Exception("duplicate"))
    )

    with pytest.raises(ConflictError, match="already belongs to an organisation"):
        run_async(
            service.create_membership(
                user_id=uuid4(),
                organisation_id=uuid4(),
                role=MembershipRole.MEMBER,
            )
        )


def test_ensure_user_can_list_organisation_memberships_allows_owner_and_admin() -> None:
    service = MembershipService(session=_session_stub())
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


def test_ensure_user_cannot_list_org_memberships_for_member_or_non_member() -> None:
    service = MembershipService(session=_session_stub())
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


def test_transfer_membership_rejects_when_user_is_last_owner() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    old = Membership(
        user_id=uuid4(),
        organisation_id=uuid4(),
        role=MembershipRole.OWNER,
    )
    service.membership_repository.get_membership_for_user = AsyncMock(return_value=old)
    service.membership_repository.count_active_owners = AsyncMock(return_value=1)

    with pytest.raises(ConflictError):
        run_async(
            service.transfer_membership(
                user_id=old.user_id,
                organisation_id=uuid4(),
                role=MembershipRole.MEMBER,
            )
        )


def test_change_membership_role_owner_can_promote_member() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    organisation_id = uuid4()
    actor_user_id = uuid4()
    target = Membership(
        user_id=uuid4(), organisation_id=organisation_id, role=MembershipRole.MEMBER
    )
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(return_value=object())
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=type("Org", (), {"status": "active"})()
    )
    service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
            role=MembershipRole.OWNER,
        )
    )
    service.membership_repository.get_membership_by_id = AsyncMock(return_value=target)
    service.membership_repository.update_role = AsyncMock(return_value=target)

    with patch(
        "app.memberships.services.memberships.AuditEventService"
    ) as audit_service_cls:
        audit_service_cls.return_value.record_event = AsyncMock()

        run_async(
            service.change_membership_role(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                audit_context=AuditContext(actor_user_id=actor_user_id),
                membership_id=uuid4(),
                role=MembershipRole.ADMIN,
            )
        )

    audit_service_cls.return_value.record_event.assert_awaited_once()


def test_change_membership_role_admin_is_forbidden() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    organisation_id = uuid4()
    actor_user_id = uuid4()
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(return_value=object())
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=type("Org", (), {"status": "active"})()
    )
    service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
            role=MembershipRole.ADMIN,
        )
    )
    service.membership_repository.get_membership_by_id = AsyncMock(
        return_value=Membership(
            user_id=uuid4(), organisation_id=organisation_id, role=MembershipRole.MEMBER
        )
    )

    with pytest.raises(ForbiddenError):
        run_async(
            service.change_membership_role(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                audit_context=AuditContext(actor_user_id=actor_user_id),
                membership_id=uuid4(),
                role=MembershipRole.ADMIN,
            )
        )


def test_change_membership_role_rejects_noop_without_audit_event() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    organisation_id = uuid4()
    actor_user_id = uuid4()
    target = Membership(
        user_id=uuid4(), organisation_id=organisation_id, role=MembershipRole.MEMBER
    )
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(return_value=object())
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=type("Org", (), {"status": "active"})()
    )
    service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
            role=MembershipRole.OWNER,
        )
    )
    service.membership_repository.get_membership_by_id = AsyncMock(return_value=target)

    with patch(
        "app.memberships.services.memberships.AuditEventService"
    ) as audit_service_cls:
        audit_service_cls.return_value.record_event = AsyncMock()
        with pytest.raises(ConflictError, match="already has this role"):
            run_async(
                service.change_membership_role(
                    organisation_id=organisation_id,
                    actor_user_id=actor_user_id,
                    audit_context=AuditContext(actor_user_id=actor_user_id),
                    membership_id=uuid4(),
                    role=MembershipRole.MEMBER,
                )
            )

    service.membership_repository.update_role.assert_not_called()
    audit_service_cls.return_value.record_event.assert_not_called()


def test_directory_service_returns_projection_objects() -> None:
    service = MembershipService(session=_session_stub())
    service.user_service = AsyncMock()
    service.user_service.get_user_by_id = AsyncMock(return_value=object())
    service.user_service.ensure_user_is_active = AsyncMock()
    service.organisation_service = AsyncMock()
    service.organisation_service.get_organisation = AsyncMock(
        return_value=type("Org", (), {"status": "active"})()
    )
    service.membership_repository = AsyncMock()
    service.membership_repository.get_membership = AsyncMock(
        return_value=Membership(
            user_id=uuid4(), organisation_id=uuid4(), role=MembershipRole.MEMBER
        )
    )
    service.membership_repository.list_directory_members_for_organisation = AsyncMock(
        return_value=[("John", "Doe", MembershipRole.ADMIN)]
    )

    items = run_async(
        service.list_directory_members_for_user(
            organisation_id=uuid4(), actor_user_id=uuid4()
        )
    )

    assert len(items) == 1
    assert items[0].display_name == "John Doe"
    assert items[0].tenant_role == MembershipRole.ADMIN
    assert not isinstance(items[0], Membership)


def test_create_membership_owner_maps_integrity_error_to_owner_conflict() -> None:
    service = MembershipService(session=_session_stub())
    service.membership_repository = AsyncMock()
    service.membership_repository.get_membership_for_user = AsyncMock(return_value=None)
    service.membership_repository.create_membership = AsyncMock(
        side_effect=IntegrityError("insert", params={}, orig=Exception("duplicate"))
    )

    with pytest.raises(ConflictError, match="already has an active owner"):
        run_async(
            service.create_membership(
                user_id=uuid4(),
                organisation_id=uuid4(),
                role=MembershipRole.OWNER,
            )
        )
