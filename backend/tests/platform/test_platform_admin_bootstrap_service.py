from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.platform.services.platform_bootstrap import (
    LOCAL_USER_NOT_FOUND_MESSAGE,
    PlatformAdminBootstrapService,
    PlatformAdminBootstrapStatus,
)
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security, pytest.mark.authz, pytest.mark.audit]

BOOTSTRAP_REASON = "Initial platform admin bootstrap"


def _bootstrap_service(migrated_session_factory, *, environment: str = "local"):
    return PlatformAdminBootstrapService(
        migrated_session_factory,
        environment_provider=lambda: environment,
    )


def _seed_user(
    migrated_session_factory,
    *,
    email: str,
    external_auth_id: str,
    status: UserStatus = UserStatus.ACTIVE,
    email_verified: bool = True,
):
    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                user = User(
                    external_auth_id=external_auth_id,
                    email=email,
                    status=status,
                    email_verified=email_verified,
                )
                session.add(user)
            return user

    return run_async(_run())


def _seed_staff(
    migrated_session_factory,
    *,
    user_id: UUID,
    role: PlatformStaffRole,
    status: PlatformStaffStatus,
):
    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                staff = PlatformStaff(
                    user_id=user_id,
                    role=role.value,
                    status=status.value,
                    suspended_at=(
                        datetime.now(UTC)
                        if status == PlatformStaffStatus.SUSPENDED
                        else None
                    ),
                    suspended_reason=(
                        "policy" if status == PlatformStaffStatus.SUSPENDED else None
                    ),
                )
                session.add(staff)
            return staff

    return run_async(_run())


def _get_staff_for_user(
    migrated_session_factory, user_id: UUID
) -> PlatformStaff | None:
    async def _run():
        async with migrated_session_factory() as session:
            return (
                await session.execute(
                    select(PlatformStaff).where(PlatformStaff.user_id == user_id)
                )
            ).scalar_one_or_none()

    return run_async(_run())


def _get_bootstrap_audit_event(migrated_session_factory) -> AuditEvent | None:
    async def _run():
        async with migrated_session_factory() as session:
            return (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action
                        == AuditAction.PLATFORM_ADMIN_BOOTSTRAPPED.value
                    )
                )
            ).scalar_one_or_none()

    return run_async(_run())


def test_bootstrap_fails_when_no_local_user_exists(migrated_session_factory) -> None:
    service = _bootstrap_service(migrated_session_factory)

    with pytest.raises(NotFoundError, match=LOCAL_USER_NOT_FOUND_MESSAGE):
        run_async(
            service.bootstrap_platform_admin_by_email(
                email="missing@example.com",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_fails_when_email_is_ambiguous_without_external_auth_id(
    migrated_session_factory,
) -> None:
    _seed_user(
        migrated_session_factory,
        email="Admin@Example.com",
        external_auth_id="kc-admin-1",
    )
    _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin-2",
    )
    service = _bootstrap_service(migrated_session_factory)

    with pytest.raises(ConflictError, match="Multiple local users match"):
        run_async(
            service.bootstrap_platform_admin_by_email(
                email=" ADMIN@example.com ",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_selects_matching_external_auth_id_for_ambiguous_email(
    migrated_session_factory,
) -> None:
    _seed_user(
        migrated_session_factory,
        email="Admin@Example.com",
        external_auth_id="kc-admin-1",
    )
    selected = _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin-2",
    )
    service = _bootstrap_service(migrated_session_factory)

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email=" ADMIN@example.com ",
            external_auth_id="kc-admin-2",
            reason=BOOTSTRAP_REASON,
        )
    )

    assert result.target_user_id == selected.id
    assert result.email == "admin@example.com"
    assert result.status == PlatformAdminBootstrapStatus.CREATED_STAFF


def test_bootstrap_fails_when_external_auth_id_does_not_match_email_user(
    migrated_session_factory,
) -> None:
    _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin-1",
    )
    service = _bootstrap_service(migrated_session_factory)

    with pytest.raises(ConflictError, match="external-auth-id"):
        run_async(
            service.bootstrap_platform_admin_by_email(
                email="admin@example.com",
                external_auth_id="kc-other",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_fails_for_suspended_local_user(migrated_session_factory) -> None:
    _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
        status=UserStatus.SUSPENDED,
    )
    service = _bootstrap_service(migrated_session_factory)

    with pytest.raises(ConflictError, match="User is suspended"):
        run_async(
            service.bootstrap_platform_admin_by_email(
                email="admin@example.com",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_fails_for_unverified_email(migrated_session_factory) -> None:
    _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
        email_verified=False,
    )
    service = _bootstrap_service(migrated_session_factory)

    with pytest.raises(ConflictError, match="email is not verified"):
        run_async(
            service.bootstrap_platform_admin_by_email(
                email="admin@example.com",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_creates_active_platform_admin_staff(
    migrated_session_factory,
) -> None:
    user = _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    service = _bootstrap_service(migrated_session_factory)

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email="admin@example.com",
            reason=BOOTSTRAP_REASON,
        )
    )

    staff = _get_staff_for_user(migrated_session_factory, user.id)
    assert staff is not None
    assert staff.id == result.platform_staff_id
    assert staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
    assert staff.status == PlatformStaffStatus.ACTIVE.value
    assert staff.created_by_user_id is None
    assert result.status == PlatformAdminBootstrapStatus.CREATED_STAFF


def test_bootstrap_is_idempotent_for_active_platform_admin(
    migrated_session_factory,
) -> None:
    user = _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    existing_staff = _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=PlatformStaffRole.PLATFORM_ADMIN,
        status=PlatformStaffStatus.ACTIVE,
    )
    service = _bootstrap_service(migrated_session_factory)

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email="admin@example.com",
            reason=BOOTSTRAP_REASON,
        )
    )

    assert result.platform_staff_id == existing_staff.id
    assert result.status == PlatformAdminBootstrapStatus.ALREADY_PLATFORM_ADMIN


def test_bootstrap_promotes_existing_non_admin_staff(migrated_session_factory) -> None:
    user = _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=PlatformStaffRole.SUPPORT_AGENT,
        status=PlatformStaffStatus.ACTIVE,
    )
    service = _bootstrap_service(migrated_session_factory)

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email="admin@example.com",
            reason=BOOTSTRAP_REASON,
        )
    )

    staff = _get_staff_for_user(migrated_session_factory, user.id)
    assert staff is not None
    assert staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
    assert staff.status == PlatformStaffStatus.ACTIVE.value
    assert result.status == PlatformAdminBootstrapStatus.PROMOTED_STAFF
    assert result.previous_role == PlatformStaffRole.SUPPORT_AGENT.value

    event = _get_bootstrap_audit_event(migrated_session_factory)
    assert event is not None
    assert event.metadata_json["previous_role"] == PlatformStaffRole.SUPPORT_AGENT.value
    assert event.metadata_json["previous_status"] == PlatformStaffStatus.ACTIVE.value


def test_bootstrap_refuses_suspended_staff_by_default(migrated_session_factory) -> None:
    user = _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=PlatformStaffRole.COMPLIANCE_OFFICER,
        status=PlatformStaffStatus.SUSPENDED,
    )
    service = _bootstrap_service(migrated_session_factory)

    with pytest.raises(ConflictError, match="Platform staff is suspended"):
        run_async(
            service.bootstrap_platform_admin_by_email(
                email="admin@example.com",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_restores_suspended_staff_when_explicitly_requested(
    migrated_session_factory,
) -> None:
    user = _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=PlatformStaffRole.COMPLIANCE_OFFICER,
        status=PlatformStaffStatus.SUSPENDED,
    )
    service = _bootstrap_service(migrated_session_factory)

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email="admin@example.com",
            reason=BOOTSTRAP_REASON,
            restore_suspended_staff=True,
        )
    )

    staff = _get_staff_for_user(migrated_session_factory, user.id)
    assert staff is not None
    assert staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
    assert staff.status == PlatformStaffStatus.ACTIVE.value
    assert staff.suspended_at is None
    assert staff.suspended_reason is None
    assert result.status == PlatformAdminBootstrapStatus.PROMOTED_STAFF


def test_bootstrap_writes_safe_system_audit_event(migrated_session_factory) -> None:
    user = _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    service = _bootstrap_service(migrated_session_factory)

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email="admin@example.com",
            reason=BOOTSTRAP_REASON,
        )
    )

    event = _get_bootstrap_audit_event(migrated_session_factory)
    assert event is not None
    assert event.actor_user_id is None
    assert event.category == "platform"
    assert event.action == "platform_admin_bootstrapped"
    assert event.target_type == "platform_staff"
    assert event.target_id == result.platform_staff_id
    assert event.reason == BOOTSTRAP_REASON
    assert event.ip_address is None
    assert event.user_agent == "platform-bootstrap-cli"
    assert event.metadata_json == {
        "actor_type": "system",
        "command": "platform_admin_bootstrap",
        "bootstrap_result": "created_staff",
        "target_user_id": str(user.id),
        "target_email": "admin@example.com",
        "new_role": "platform_admin",
        "new_status": "active",
    }


def test_bootstrap_refuses_prod_without_confirmation(migrated_session_factory) -> None:
    _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    service = _bootstrap_service(migrated_session_factory, environment="prod")

    with pytest.raises(ConflictError, match="confirm-production"):
        run_async(
            service.bootstrap_platform_admin_by_email(
                email="admin@example.com",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_allows_prod_with_confirmation(migrated_session_factory) -> None:
    _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    service = _bootstrap_service(migrated_session_factory, environment="prod")

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email="admin@example.com",
            reason=BOOTSTRAP_REASON,
            confirm_production=True,
        )
    )

    assert result.status == PlatformAdminBootstrapStatus.CREATED_STAFF


def test_bootstrap_staff_creation_runs_inside_active_transaction(
    migrated_session_factory, monkeypatch
) -> None:
    _seed_user(
        migrated_session_factory,
        email="admin@example.com",
        external_auth_id="kc-admin",
    )
    service = _bootstrap_service(migrated_session_factory)
    original_create_staff = PlatformStaffRepository.create_staff
    observed_in_transaction = False

    async def observing_create_staff(self, *args, **kwargs):
        nonlocal observed_in_transaction
        observed_in_transaction = self.session.in_transaction()
        return await original_create_staff(self, *args, **kwargs)

    monkeypatch.setattr(
        PlatformStaffRepository,
        "create_staff",
        observing_create_staff,
    )

    result = run_async(
        service.bootstrap_platform_admin_by_email(
            email="admin@example.com",
            reason=BOOTSTRAP_REASON,
        )
    )

    assert result.status == PlatformAdminBootstrapStatus.CREATED_STAFF
    assert observed_in_transaction is True
