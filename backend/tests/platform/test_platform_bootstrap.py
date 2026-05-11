from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.platform.cli.bootstrap_admin import _amain, build_parser
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.platform.services.platform_bootstrap import (
    PlatformAdminBootstrapService,
    PlatformAdminBootstrapStatus,
)
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security, pytest.mark.authz, pytest.mark.audit]

BOOTSTRAP_REASON = "Initial platform admin bootstrap"


def _service(migrated_session_factory, *, environment: str = "local"):
    return PlatformAdminBootstrapService(
        migrated_session_factory,
        environment=environment,
    )


def _seed_user(
    migrated_session_factory,
    *,
    email: str,
    external_auth_id: str | None = None,
    status: UserStatus = UserStatus.ACTIVE,
    email_verified: bool = True,
):
    async def _run():
        async with migrated_session_factory() as session:
            async with session.begin():
                user = User(
                    external_auth_id=external_auth_id or f"kc-{email}",
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
    user_id,
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
                    suspended_reason=(
                        "security review"
                        if status == PlatformStaffStatus.SUSPENDED
                        else None
                    ),
                )
                session.add(staff)
            return staff

    return run_async(_run())


def _staff_rows_for_user(migrated_session_factory, user_id):
    async def _run():
        async with migrated_session_factory() as session:
            return list(
                (
                    await session.execute(
                        select(PlatformStaff).where(PlatformStaff.user_id == user_id)
                    )
                ).scalars()
            )

    return run_async(_run())


def _audit_events_for_staff(migrated_session_factory, staff_id):
    async def _run():
        async with migrated_session_factory() as session:
            return list(
                (
                    await session.execute(
                        select(AuditEvent).where(AuditEvent.target_id == staff_id)
                    )
                ).scalars()
            )

    return run_async(_run())


def test_bootstrap_fails_when_no_local_user_exists(migrated_session_factory):
    with pytest.raises(NotFoundError, match="Local user not found"):
        run_async(
            _service(migrated_session_factory).bootstrap_platform_admin_by_email(
                email="missing@example.com",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_fails_when_multiple_users_match_without_external_auth_id(
    migrated_session_factory,
):
    _seed_user(
        migrated_session_factory,
        email="Duplicate@Example.com",
        external_auth_id="kc-duplicate-1",
    )
    _seed_user(
        migrated_session_factory,
        email="duplicate@example.com",
        external_auth_id="kc-duplicate-2",
    )

    with pytest.raises(ConflictError, match="Multiple local users match"):
        run_async(
            _service(migrated_session_factory).bootstrap_platform_admin_by_email(
                email=" duplicate@example.com ",
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_selects_matching_external_auth_id_when_email_is_ambiguous(
    migrated_session_factory,
):
    first = _seed_user(
        migrated_session_factory,
        email="ambiguous@example.com",
        external_auth_id="kc-ambiguous-1",
    )
    selected = _seed_user(
        migrated_session_factory,
        email="Ambiguous@Example.com",
        external_auth_id="kc-ambiguous-2",
    )

    result = run_async(
        _service(migrated_session_factory).bootstrap_platform_admin_by_email(
            email=" ambiguous@example.com ",
            reason=BOOTSTRAP_REASON,
            external_auth_id="kc-ambiguous-2",
        )
    )

    assert result.target_user_id == selected.id
    assert _staff_rows_for_user(migrated_session_factory, first.id) == []
    assert len(_staff_rows_for_user(migrated_session_factory, selected.id)) == 1


def test_bootstrap_fails_when_external_auth_id_does_not_match_email_user(
    migrated_session_factory,
):
    _seed_user(
        migrated_session_factory,
        email="selected@example.com",
        external_auth_id="kc-selected",
    )

    with pytest.raises(ConflictError, match="External auth ID"):
        run_async(
            _service(migrated_session_factory).bootstrap_platform_admin_by_email(
                email="selected@example.com",
                reason=BOOTSTRAP_REASON,
                external_auth_id="kc-other",
            )
        )


def test_bootstrap_fails_for_suspended_local_user(migrated_session_factory):
    user = _seed_user(
        migrated_session_factory,
        email="suspended@example.com",
        status=UserStatus.SUSPENDED,
    )

    with pytest.raises(ConflictError, match="User is not active"):
        run_async(
            _service(migrated_session_factory).bootstrap_platform_admin_by_email(
                email=user.email,
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_fails_for_unverified_email(migrated_session_factory):
    user = _seed_user(
        migrated_session_factory,
        email="unverified@example.com",
        email_verified=False,
    )

    with pytest.raises(ConflictError, match="User email is not verified"):
        run_async(
            _service(migrated_session_factory).bootstrap_platform_admin_by_email(
                email=user.email,
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_creates_active_platform_admin_staff(migrated_session_factory):
    user = _seed_user(migrated_session_factory, email="create@example.com")

    result = run_async(
        _service(migrated_session_factory).bootstrap_platform_admin_by_email(
            email=" CREATE@example.com ",
            reason=BOOTSTRAP_REASON,
        )
    )

    assert result.status == PlatformAdminBootstrapStatus.CREATED_STAFF
    assert result.target_user_id == user.id
    assert result.target_email == "create@example.com"
    staff_rows = _staff_rows_for_user(migrated_session_factory, user.id)
    assert len(staff_rows) == 1
    assert staff_rows[0].role == PlatformStaffRole.PLATFORM_ADMIN.value
    assert staff_rows[0].status == PlatformStaffStatus.ACTIVE.value
    assert staff_rows[0].created_by_user_id is None


def test_bootstrap_is_idempotent_for_existing_active_platform_admin(
    migrated_session_factory,
):
    user = _seed_user(migrated_session_factory, email="idempotent@example.com")
    _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=PlatformStaffRole.PLATFORM_ADMIN,
        status=PlatformStaffStatus.ACTIVE,
    )

    result = run_async(
        _service(migrated_session_factory).bootstrap_platform_admin_by_email(
            email=user.email,
            reason=BOOTSTRAP_REASON,
        )
    )

    assert result.status == PlatformAdminBootstrapStatus.ALREADY_PLATFORM_ADMIN
    assert len(_staff_rows_for_user(migrated_session_factory, user.id)) == 1


@pytest.mark.parametrize(
    "role",
    [PlatformStaffRole.SUPPORT_AGENT, PlatformStaffRole.COMPLIANCE_OFFICER],
)
def test_bootstrap_promotes_existing_non_admin_staff(migrated_session_factory, role):
    user = _seed_user(migrated_session_factory, email=f"{role.value}@example.com")
    _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=role,
        status=PlatformStaffStatus.ACTIVE,
    )

    result = run_async(
        _service(migrated_session_factory).bootstrap_platform_admin_by_email(
            email=user.email,
            reason=BOOTSTRAP_REASON,
        )
    )

    staff_rows = _staff_rows_for_user(migrated_session_factory, user.id)
    assert result.status == PlatformAdminBootstrapStatus.PROMOTED_STAFF
    assert result.previous_role == role.value
    assert staff_rows[0].role == PlatformStaffRole.PLATFORM_ADMIN.value
    assert staff_rows[0].status == PlatformStaffStatus.ACTIVE.value


def test_bootstrap_refuses_suspended_platform_staff_by_default(
    migrated_session_factory,
):
    user = _seed_user(migrated_session_factory, email="staff-suspended@example.com")
    _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=PlatformStaffRole.SUPPORT_AGENT,
        status=PlatformStaffStatus.SUSPENDED,
    )

    with pytest.raises(ConflictError, match="Platform staff is suspended"):
        run_async(
            _service(migrated_session_factory).bootstrap_platform_admin_by_email(
                email=user.email,
                reason=BOOTSTRAP_REASON,
            )
        )


def test_bootstrap_can_restore_suspended_platform_staff_when_explicit(
    migrated_session_factory,
):
    user = _seed_user(migrated_session_factory, email="restore-staff@example.com")
    _seed_staff(
        migrated_session_factory,
        user_id=user.id,
        role=PlatformStaffRole.SUPPORT_AGENT,
        status=PlatformStaffStatus.SUSPENDED,
    )

    result = run_async(
        _service(migrated_session_factory).bootstrap_platform_admin_by_email(
            email=user.email,
            reason=BOOTSTRAP_REASON,
            restore_suspended_staff=True,
        )
    )

    staff = _staff_rows_for_user(migrated_session_factory, user.id)[0]
    assert result.status == PlatformAdminBootstrapStatus.PROMOTED_STAFF
    assert result.previous_status == PlatformStaffStatus.SUSPENDED.value
    assert staff.status == PlatformStaffStatus.ACTIVE.value
    assert staff.suspended_at is None
    assert staff.suspended_reason is None


def test_bootstrap_writes_safe_system_audit_event(migrated_session_factory):
    user = _seed_user(migrated_session_factory, email="audit@example.com")

    result = run_async(
        _service(migrated_session_factory).bootstrap_platform_admin_by_email(
            email=user.email,
            reason=BOOTSTRAP_REASON,
        )
    )

    events = _audit_events_for_staff(migrated_session_factory, result.platform_staff_id)
    assert len(events) == 1
    event = events[0]
    assert event.actor_user_id is None
    assert event.category == AuditCategory.PLATFORM.value
    assert event.action == AuditAction.PLATFORM_ADMIN_BOOTSTRAPPED.value
    assert event.target_type == AuditTargetType.PLATFORM_STAFF.value
    assert event.target_id == result.platform_staff_id
    assert event.reason == BOOTSTRAP_REASON
    assert event.ip_address is None
    assert event.user_agent == "platform-bootstrap-cli"
    assert event.metadata_json == {
        "actor_type": "system",
        "command": "platform_admin_bootstrap",
        "bootstrap_result": "created_staff",
        "target_user_id": str(user.id),
        "target_email": "audit@example.com",
        "new_role": PlatformStaffRole.PLATFORM_ADMIN.value,
        "new_status": PlatformStaffStatus.ACTIVE.value,
    }


def test_bootstrap_refuses_prod_without_confirmation(migrated_session_factory):
    user = _seed_user(migrated_session_factory, email="prod-refuse@example.com")

    with pytest.raises(ConflictError, match="Production bootstrap requires"):
        run_async(
            _service(
                migrated_session_factory, environment="prod"
            ).bootstrap_platform_admin_by_email(
                email=user.email,
                reason=BOOTSTRAP_REASON,
            )
        )

    assert _staff_rows_for_user(migrated_session_factory, user.id) == []


def test_bootstrap_allows_prod_with_confirmation(migrated_session_factory):
    user = _seed_user(migrated_session_factory, email="prod-allow@example.com")

    result = run_async(
        _service(
            migrated_session_factory, environment="prod"
        ).bootstrap_platform_admin_by_email(
            email=user.email,
            reason=BOOTSTRAP_REASON,
            confirm_production=True,
        )
    )

    assert result.status == PlatformAdminBootstrapStatus.CREATED_STAFF


def test_bootstrap_mutation_runs_inside_service_owned_transaction(
    migrated_session_factory,
    monkeypatch,
):
    user = _seed_user(migrated_session_factory, email="transaction@example.com")
    original_create_staff = PlatformStaffRepository.create_staff
    observed_in_transaction = False

    async def observing_create_staff(self, *args, **kwargs):
        nonlocal observed_in_transaction
        observed_in_transaction = self.session.in_transaction()
        return await original_create_staff(self, *args, **kwargs)

    monkeypatch.setattr(PlatformStaffRepository, "create_staff", observing_create_staff)

    run_async(
        _service(migrated_session_factory).bootstrap_platform_admin_by_email(
            email=user.email,
            reason=BOOTSTRAP_REASON,
        )
    )

    assert observed_in_transaction is True


def test_cli_parser_requires_email_and_reason():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--reason", BOOTSTRAP_REASON])
    with pytest.raises(SystemExit):
        parser.parse_args(["--email", "admin@example.com"])


def test_cli_returns_validation_failure_without_stacktrace(
    migrated_database_url,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)

    exit_code = run_async(
        _amain(
            [
                "--email",
                "missing@example.com",
                "--reason",
                BOOTSTRAP_REASON,
            ]
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Local user not found" in captured.err
    assert "Traceback" not in captured.err
