from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditEvent, AuditTargetType
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.privacy.erasures.execution import (
    ErasureExecutionError,
    execute_approved_erasure_request_by_staff,
)
from app.privacy.erasures.orchestrator import ErasureOrchestrationStatus
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.privacy.services.data_subject_requests import DataSubjectRequestService
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_user(
    session,
    *,
    email: str | None = None,
    status: str = UserStatus.ACTIVE.value,
) -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email or f"subject-{uuid4()}@example.com",
        email_verified=True,
        first_name="Subject",
        last_name="User",
        onboarding_completed=True,
        status=status,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _dsr_for_user(user: User) -> DataSubjectRequest:
    now = datetime.now(UTC)
    return DataSubjectRequest(
        request_type="erase",
        status=DataSubjectRequestStatus.APPROVED.value,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=now,
        reviewed_at=now,
        decided_at=now,
        due_at=now + timedelta(days=30),
    )


def _staff_record(
    user: User,
    *,
    role: str = PlatformStaffRole.COMPLIANCE_OFFICER.value,
    status: str = PlatformStaffStatus.ACTIVE.value,
) -> PlatformStaff:
    return PlatformStaff(
        user_id=user.id,
        role=role,
        status=status,
    )


def _invite_payload(*, invite_id: UUID, email: str) -> dict[str, object]:
    return {
        "invite_id": str(invite_id),
        "organisation_id": str(uuid4()),
        "email": email,
        "encrypted_raw_token": "encrypted-secret-token",
        "purpose": "created",
        "role": "member",
        "debug_note": "free text with possible PII",
    }


def _outbox_event(
    *,
    invite_id: UUID,
    email: str,
    status: str = OutboxStatus.PENDING.value,
) -> OutboxEvent:
    return OutboxEvent(
        event_type=OutboxEventType.INVITE_CREATED.value,
        aggregate_type="invite",
        aggregate_id=invite_id,
        payload_json=_invite_payload(invite_id=invite_id, email=email),
        status=status,
        locked_at=(
            datetime.now(UTC) if status == OutboxStatus.PROCESSING.value else None
        ),
    )


async def _execution_audit_events(
    session,
    *,
    request_id: UUID,
) -> tuple[AuditEvent, ...]:
    stmt = (
        select(AuditEvent)
        .where(
            AuditEvent.action
            == AuditAction.DATA_SUBJECT_REQUEST_ERASURE_EXECUTED.value,
            AuditEvent.target_type == AuditTargetType.DATA_SUBJECT_REQUEST.value,
            AuditEvent.target_id == request_id,
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    return tuple((await session.execute(stmt)).scalars().all())


def test_erasure_execution_authorises_privileged_staff_and_runs_orchestrator(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"subject-{uuid4()}@example.com"
            subject = await _create_user(session, email=subject_email)
            executor = await _create_user(session)
            staff = _staff_record(executor)
            dsr = _dsr_for_user(subject)
            outbox = _outbox_event(invite_id=uuid4(), email=subject_email)
            session.add_all([staff, dsr, outbox])
            await session.flush()

            result = await execute_approved_erasure_request_by_staff(
                session,
                request_id=dsr.id,
                executor_user_id=executor.id,
            )
            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            audit_events = await _execution_audit_events(session, request_id=dsr.id)

            assert result.orchestration_status is ErasureOrchestrationStatus.COMPLETED
            assert result.executor_user_id == executor.id
            assert result.executor_role == PlatformStaffRole.COMPLIANCE_OFFICER.value
            assert result.provider_keys == (
                "audit.minimise_subject_actor_or_target_identifiers",
                "outbox.purge_or_scrub_payload",
                "invites.anonymise_or_purge_subject_references",
                "users.anonymise_profile",
            )
            assert result.did_mutate is True
            assert result.failure_reason_code is None
            assert result.audit_event_id == audit_events[0].id
            assert dsr.execution_status == DataSubjectRequestExecutionStatus.READY.value
            assert subject.email is None
            assert subject.external_auth_id == f"erased-user:{subject.id}"
            assert outbox.status == OutboxStatus.FAILED.value
            assert "email" not in outbox.payload_json
            assert "encrypted_raw_token" not in outbox.payload_json
            assert len(audit_events) == 1
            assert audit_events[0].actor_user_id == executor.id
            assert audit_events[0].target_id == dsr.id
            assert audit_events[0].metadata_json == {
                "orchestration_status": "completed",
                "provider_keys": list(result.provider_keys),
                "affected_rows": result.affected_rows,
                "did_mutate": True,
            }

    run_async(_run())


def test_erasure_execution_rejects_self_erasure_without_mutation(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"self-erasure-{uuid4()}@example.com"
            subject = await _create_user(session, email=subject_email)
            staff = _staff_record(subject)
            dsr = _dsr_for_user(subject)
            outbox = _outbox_event(invite_id=uuid4(), email=subject_email)
            session.add_all([staff, dsr, outbox])
            await session.flush()

            with pytest.raises(ErasureExecutionError) as exc_info:
                await execute_approved_erasure_request_by_staff(
                    session,
                    request_id=dsr.id,
                    executor_user_id=subject.id,
                )

            assert exc_info.value.reason_code == (
                "erasure_execution_requires_non_subject_executor"
            )
            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            audit_events = await _execution_audit_events(session, request_id=dsr.id)
            assert subject.email == subject_email
            assert subject.external_auth_id.startswith("kc|")
            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.NOT_STARTED.value
            )
            assert outbox.status == OutboxStatus.PENDING.value
            assert outbox.payload_json["email"] == subject_email
            assert audit_events == ()

    run_async(_run())


@pytest.mark.parametrize(
    ("role", "staff_status", "user_status", "expected_reason"),
    [
        (
            PlatformStaffRole.SUPPORT_AGENT.value,
            PlatformStaffStatus.ACTIVE.value,
            UserStatus.ACTIVE.value,
            "requires_privileged_staff",
        ),
        (
            PlatformStaffRole.PLATFORM_ADMIN.value,
            PlatformStaffStatus.SUSPENDED.value,
            UserStatus.ACTIVE.value,
            "requires_active_staff",
        ),
        (
            PlatformStaffRole.PLATFORM_ADMIN.value,
            PlatformStaffStatus.ACTIVE.value,
            UserStatus.SUSPENDED.value,
            "requires_active_user",
        ),
    ],
)
def test_erasure_execution_rejects_unauthorised_staff_without_mutation(
    migrated_session_factory,
    role: str,
    staff_status: str,
    user_status: str,
    expected_reason: str,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"subject-{uuid4()}@example.com"
            subject = await _create_user(session, email=subject_email)
            executor = await _create_user(session, status=user_status)
            staff = _staff_record(executor, role=role, status=staff_status)
            dsr = _dsr_for_user(subject)
            outbox = _outbox_event(invite_id=uuid4(), email=subject_email)
            session.add_all([staff, dsr, outbox])
            await session.flush()

            with pytest.raises(ErasureExecutionError) as exc_info:
                await execute_approved_erasure_request_by_staff(
                    session,
                    request_id=dsr.id,
                    executor_user_id=executor.id,
                )

            assert expected_reason in exc_info.value.reason_code
            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            audit_events = await _execution_audit_events(session, request_id=dsr.id)
            assert subject.email == subject_email
            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.NOT_STARTED.value
            )
            assert outbox.status == OutboxStatus.PENDING.value
            assert outbox.payload_json["email"] == subject_email
            assert audit_events == ()

    run_async(_run())


def test_erasure_execution_rejects_non_staff_executor(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject = await _create_user(session)
            executor = await _create_user(session)
            dsr = _dsr_for_user(subject)
            session.add(dsr)
            await session.flush()

            with pytest.raises(ErasureExecutionError) as exc_info:
                await execute_approved_erasure_request_by_staff(
                    session,
                    request_id=dsr.id,
                    executor_user_id=executor.id,
                )

            assert exc_info.value.reason_code == (
                "erasure_execution_requires_platform_staff"
            )
            assert await _execution_audit_events(session, request_id=dsr.id) == ()

    run_async(_run())


def test_erasure_execution_returns_failed_result_from_orchestrator(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                subject_email = f"processing-{uuid4()}@example.com"
                subject = await _create_user(session, email=subject_email)
                executor = await _create_user(session)
                staff = _staff_record(executor)
                dsr = _dsr_for_user(subject)
                outbox = _outbox_event(
                    invite_id=uuid4(),
                    email=subject_email,
                    status=OutboxStatus.PROCESSING.value,
                )
                session.add_all([staff, dsr, outbox])
                await session.flush()

                result = await execute_approved_erasure_request_by_staff(
                    session,
                    request_id=dsr.id,
                    executor_user_id=executor.id,
                )
                audit_events = await _execution_audit_events(
                    session,
                    request_id=dsr.id,
                )
                assert result.orchestration_status is ErasureOrchestrationStatus.FAILED
                assert result.failure_reason_code == (
                    "outbox_erasure_processing_rows_in_flight"
                )
                assert result.affected_rows == 0
                assert result.audit_event_id == audit_events[0].id
                assert len(audit_events) == 1
                assert audit_events[0].actor_user_id == executor.id
                assert audit_events[0].metadata_json == {
                    "orchestration_status": "failed",
                    "provider_keys": [],
                    "affected_rows": 0,
                    "did_mutate": False,
                    "failure_reason_code": ("outbox_erasure_processing_rows_in_flight"),
                }

            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            persisted_events = await _execution_audit_events(session, request_id=dsr.id)
            assert subject.email == subject_email
            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert dsr.execution_failure_reason_code == (
                "outbox_erasure_processing_rows_in_flight"
            )
            assert outbox.status == OutboxStatus.PROCESSING.value
            assert "email" in outbox.payload_json
            assert len(persisted_events) == 1

    run_async(_run())


def test_erasure_execution_rejects_missing_request(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            executor = await _create_user(session)
            staff = _staff_record(executor)
            session.add(staff)
            await session.flush()

            with pytest.raises(ErasureExecutionError) as exc_info:
                await execute_approved_erasure_request_by_staff(
                    session,
                    request_id=uuid4(),
                    executor_user_id=executor.id,
                )

            assert exc_info.value.reason_code == "erasure_execution_request_not_found"

    run_async(_run())


def test_dsr_service_auto_fulfils_successful_erasure_execution(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"service-erasure-{uuid4()}@example.com"
            subject = await _create_user(session, email=subject_email)
            executor = await _create_user(session)
            staff = _staff_record(executor)
            dsr = _dsr_for_user(subject)
            outbox = _outbox_event(invite_id=uuid4(), email=subject_email)
            session.add_all([staff, dsr, outbox])
            await session.flush()

            result = await DataSubjectRequestService(
                session
            ).execute_approved_erasure_request_by_platform_staff(
                request_id=dsr.id,
                executor_user_id=executor.id,
                audit_context=AuditContext(actor_user_id=executor.id),
            )

            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            execution_events = await _execution_audit_events(
                session,
                request_id=dsr.id,
            )
            fulfilment_events = (
                (
                    await session.execute(
                        select(AuditEvent).where(
                            AuditEvent.action
                            == AuditAction.DATA_SUBJECT_REQUEST_FULFILLED.value,
                            AuditEvent.target_type
                            == AuditTargetType.DATA_SUBJECT_REQUEST.value,
                            AuditEvent.target_id == dsr.id,
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert result.status == DataSubjectRequestStatus.FULFILLED.value
            assert result.execution_status == (
                DataSubjectRequestExecutionStatus.READY.value
            )
            assert result.fulfilled_at is not None
            assert dsr.status == DataSubjectRequestStatus.FULFILLED.value
            assert dsr.execution_status == DataSubjectRequestExecutionStatus.READY.value
            assert dsr.fulfilled_at is not None
            assert dsr.reviewer_user_id == executor.id
            assert subject.email is None
            assert subject.external_auth_id == f"erased-user:{subject.id}"
            assert outbox.status == OutboxStatus.FAILED.value
            assert len(execution_events) == 1
            assert execution_events[0].actor_user_id == executor.id
            assert len(fulfilment_events) == 1
            assert fulfilment_events[0].actor_user_id == executor.id
            assert fulfilment_events[0].target_id == dsr.id

    run_async(_run())


def test_dsr_service_maps_missing_erasure_request_to_not_found(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            executor = await _create_user(session)
            staff = _staff_record(executor)
            session.add(staff)
            await session.flush()

            with pytest.raises(NotFoundError):
                await DataSubjectRequestService(
                    session
                ).execute_approved_erasure_request_by_platform_staff(
                    request_id=uuid4(),
                    executor_user_id=executor.id,
                    audit_context=AuditContext(actor_user_id=executor.id),
                )

    run_async(_run())


def test_dsr_service_maps_self_erasure_to_forbidden(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"service-self-erasure-{uuid4()}@example.com"
            subject = await _create_user(session, email=subject_email)
            staff = _staff_record(subject)
            dsr = _dsr_for_user(subject)
            outbox = _outbox_event(invite_id=uuid4(), email=subject_email)
            session.add_all([staff, dsr, outbox])
            await session.flush()

            with pytest.raises(ForbiddenError):
                await DataSubjectRequestService(
                    session
                ).execute_approved_erasure_request_by_platform_staff(
                    request_id=dsr.id,
                    executor_user_id=subject.id,
                    audit_context=AuditContext(actor_user_id=subject.id),
                )

            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            audit_events = await _execution_audit_events(session, request_id=dsr.id)
            assert subject.email == subject_email
            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.NOT_STARTED.value
            )
            assert outbox.status == OutboxStatus.PENDING.value
            assert audit_events == ()

    run_async(_run())


def test_dsr_service_maps_stale_executor_state_to_forbidden(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"subject-{uuid4()}@example.com"
            subject = await _create_user(session, email=subject_email)
            executor = await _create_user(session)
            staff = _staff_record(
                executor,
                role=PlatformStaffRole.SUPPORT_AGENT.value,
            )
            dsr = _dsr_for_user(subject)
            outbox = _outbox_event(invite_id=uuid4(), email=subject_email)
            session.add_all([staff, dsr, outbox])
            await session.flush()

            with pytest.raises(ForbiddenError):
                await DataSubjectRequestService(
                    session
                ).execute_approved_erasure_request_by_platform_staff(
                    request_id=dsr.id,
                    executor_user_id=executor.id,
                    audit_context=AuditContext(actor_user_id=executor.id),
                )

            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            audit_events = await _execution_audit_events(session, request_id=dsr.id)
            assert subject.email == subject_email
            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.NOT_STARTED.value
            )
            assert outbox.status == OutboxStatus.PENDING.value
            assert audit_events == ()

    run_async(_run())


def test_dsr_service_maps_ineligible_erasure_request_to_conflict(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject = await _create_user(session)
            executor = await _create_user(session)
            staff = _staff_record(executor)
            dsr = _dsr_for_user(subject)
            dsr.request_type = "export"
            session.add_all([staff, dsr])
            await session.flush()

            with pytest.raises(ConflictError) as exc_info:
                await DataSubjectRequestService(
                    session
                ).execute_approved_erasure_request_by_platform_staff(
                    request_id=dsr.id,
                    executor_user_id=executor.id,
                    audit_context=AuditContext(actor_user_id=executor.id),
                )

            assert exc_info.value.detail == (
                "Erasure execution is not eligible in the current state"
            )
            assert exc_info.value.extra == {
                "reason_code": "erasure_orchestration_requires_erase_request"
            }
            assert await _execution_audit_events(session, request_id=dsr.id) == ()

    run_async(_run())
