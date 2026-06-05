from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

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
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_user(session, *, email: str | None = None) -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email or f"subject-{uuid4()}@example.com",
        email_verified=True,
        first_name="Subject",
        last_name="User",
        onboarding_completed=True,
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
            assert dsr.execution_status == DataSubjectRequestExecutionStatus.READY.value
            assert subject.email is None
            assert subject.external_auth_id == f"erased-user:{subject.id}"
            assert outbox.status == OutboxStatus.FAILED.value
            assert "email" not in outbox.payload_json
            assert "encrypted_raw_token" not in outbox.payload_json

    run_async(_run())


@pytest.mark.parametrize(
    ("role", "status", "expected_reason"),
    [
        (
            PlatformStaffRole.SUPPORT_AGENT.value,
            PlatformStaffStatus.ACTIVE.value,
            "requires_privileged_staff",
        ),
        (
            PlatformStaffRole.PLATFORM_ADMIN.value,
            PlatformStaffStatus.SUSPENDED.value,
            "requires_active_staff",
        ),
    ],
)
def test_erasure_execution_rejects_unauthorised_staff_without_mutation(
    migrated_session_factory,
    role: str,
    status: str,
    expected_reason: str,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"subject-{uuid4()}@example.com"
            subject = await _create_user(session, email=subject_email)
            executor = await _create_user(session)
            staff = _staff_record(executor, role=role, status=status)
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
            assert subject.email == subject_email
            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.NOT_STARTED.value
            )
            assert outbox.status == OutboxStatus.PENDING.value
            assert outbox.payload_json["email"] == subject_email

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
                assert result.orchestration_status is ErasureOrchestrationStatus.FAILED
                assert result.failure_reason_code == (
                    "outbox_erasure_processing_rows_in_flight"
                )
                assert result.affected_rows == 0

            await session.refresh(subject)
            await session.refresh(dsr)
            await session.refresh(outbox)
            assert subject.email == subject_email
            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert dsr.execution_failure_reason_code == (
                "outbox_erasure_processing_rows_in_flight"
            )
            assert outbox.status == OutboxStatus.PROCESSING.value
            assert "email" in outbox.payload_json

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
