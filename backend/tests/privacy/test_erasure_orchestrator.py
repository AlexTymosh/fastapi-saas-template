from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.privacy.erasures.orchestrator import (
    ErasureOrchestrationError,
    ErasureOrchestrationStatus,
    execute_core_erasure_for_approved_request,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


def _normalise_test_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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


def _dsr_for_user(
    user: User,
    *,
    request_type: str = "erase",
    status: str = DataSubjectRequestStatus.APPROVED.value,
) -> DataSubjectRequest:
    now = datetime.now(UTC)
    return DataSubjectRequest(
        request_type=request_type,
        status=status,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=now,
        reviewed_at=now if status == DataSubjectRequestStatus.APPROVED.value else None,
        decided_at=now if status == DataSubjectRequestStatus.APPROVED.value else None,
        due_at=now + timedelta(days=30),
    )


def _dsr_for_missing_subject() -> DataSubjectRequest:
    now = datetime.now(UTC)
    return DataSubjectRequest(
        request_type="erase",
        status=DataSubjectRequestStatus.APPROVED.value,
        requester_user_id=uuid4(),
        subject_user_id=uuid4(),
        submitted_at=now,
        reviewed_at=now,
        decided_at=now,
        due_at=now + timedelta(days=30),
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


async def _get_outbox_event_by_aggregate_id(
    session,
    aggregate_id: UUID,
) -> OutboxEvent | None:
    stmt = select(OutboxEvent).where(OutboxEvent.aggregate_id == aggregate_id)
    return (await session.execute(stmt)).scalar_one_or_none()


def test_core_erasure_orchestrator_runs_providers_in_safe_order(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"subject-{uuid4()}@example.com"
            user = await _create_user(session, email=subject_email)
            dsr = _dsr_for_user(user)
            invite_id = uuid4()
            event = _outbox_event(invite_id=invite_id, email=subject_email)
            session.add_all([dsr, event])
            await session.flush()

            result = await execute_core_erasure_for_approved_request(session, dsr)
            await session.refresh(dsr)
            await session.refresh(user)
            await session.refresh(event)

            assert result.status is ErasureOrchestrationStatus.COMPLETED
            assert result.failure_reason_code is None
            assert result.provider_keys == (
                "outbox.purge_or_scrub_payload",
                "invites.anonymise_or_purge_subject_references",
                "users.anonymise_profile",
            )
            assert result.did_mutate is True
            assert dsr.execution_status == DataSubjectRequestExecutionStatus.READY.value
            assert dsr.execution_completed_at is not None
            assert dsr.execution_failed_at is None
            assert user.email is None
            assert user.external_auth_id == f"erased-user:{user.id}"
            assert event.status == OutboxStatus.FAILED.value
            assert event.last_error == "privacy_erasure_scrubbed"
            assert "email" not in event.payload_json
            assert "encrypted_raw_token" not in event.payload_json

    run_async(_run())


def test_core_erasure_orchestrator_locks_subject_before_snapshot(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        old_email = f"old-{uuid4()}@example.com"
        new_email = f"new-{uuid4()}@example.com"
        invite_id = uuid4()
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=old_email)
            dsr = _dsr_for_user(user)
            session.add(dsr)
            await session.commit()

            stale_subject = await session.get(User, user.id)
            assert stale_subject is not None
            assert stale_subject.email == old_email
            await session.commit()

            async with migrated_session_factory() as other_session:
                async with other_session.begin():
                    fresh_subject = await other_session.get(User, user.id)
                    assert fresh_subject is not None
                    fresh_subject.email = new_email
                    other_session.add(
                        _outbox_event(invite_id=invite_id, email=new_email)
                    )

            result = await execute_core_erasure_for_approved_request(session, dsr)
            event = await _get_outbox_event_by_aggregate_id(session, invite_id)
            assert event is not None

            assert result.status is ErasureOrchestrationStatus.COMPLETED
            assert stale_subject.email is None
            assert event.status == OutboxStatus.FAILED.value
            assert "email" not in event.payload_json
            assert "encrypted_raw_token" not in event.payload_json

    run_async(_run())


def test_core_erasure_orchestrator_is_idempotent_after_ready(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(user)
            dsr.execution_status = DataSubjectRequestExecutionStatus.READY.value
            dsr.execution_completed_at = datetime.now(UTC)
            session.add(dsr)
            await session.flush()

            result = await execute_core_erasure_for_approved_request(session, dsr)

            assert result.status is ErasureOrchestrationStatus.ALREADY_COMPLETED
            assert result.provider_results == ()
            assert result.did_mutate is False
            assert result.failure_reason_code is None

    run_async(_run())


def test_core_erasure_orchestrator_returns_failed_result_for_provider_failure(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                subject_email = f"processing-{uuid4()}@example.com"
                user = await _create_user(session, email=subject_email)
                dsr = _dsr_for_user(user)
                event = _outbox_event(
                    invite_id=uuid4(),
                    email=subject_email,
                    status=OutboxStatus.PROCESSING.value,
                )
                session.add_all([dsr, event])
                await session.flush()

                result = await execute_core_erasure_for_approved_request(
                    session,
                    dsr,
                )
                assert result.status is ErasureOrchestrationStatus.FAILED
                assert result.failure_reason_code == (
                    "outbox_erasure_processing_rows_in_flight"
                )
                assert result.provider_results == ()

            await session.refresh(dsr)
            await session.refresh(user)
            await session.refresh(event)
            assert (
                dsr.execution_status == DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert dsr.execution_failure_reason_code == (
                "outbox_erasure_processing_rows_in_flight"
            )
            assert dsr.execution_failed_at is not None
            assert _normalise_test_timestamp(dsr.execution_failed_at)
            assert user.email == subject_email
            assert event.status == OutboxStatus.PROCESSING.value
            assert "email" in event.payload_json
            assert "encrypted_raw_token" in event.payload_json

    run_async(_run())


def test_core_erasure_orchestrator_returns_failed_for_missing_subject(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                dsr = _dsr_for_missing_subject()
                session.add(dsr)
                await session.flush()

                result = await execute_core_erasure_for_approved_request(
                    session,
                    dsr,
                )
                assert result.status is ErasureOrchestrationStatus.FAILED
                assert result.failure_reason_code == (
                    "erasure_orchestration_subject_not_found"
                )

            await session.refresh(dsr)
            assert (
                dsr.execution_status == DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert dsr.execution_failure_reason_code == (
                "erasure_orchestration_subject_not_found"
            )

    run_async(_run())


@pytest.mark.parametrize(
    ("request_type", "status", "expected_reason"),
    [
        ("export", DataSubjectRequestStatus.APPROVED.value, "requires_erase"),
        ("erase", DataSubjectRequestStatus.SUBMITTED.value, "requires_approved"),
    ],
)
def test_core_erasure_orchestrator_rejects_ineligible_requests(
    migrated_session_factory,
    request_type: str,
    status: str,
    expected_reason: str,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(user, request_type=request_type, status=status)
            session.add(dsr)
            await session.flush()

            with pytest.raises(ErasureOrchestrationError) as exc_info:
                await execute_core_erasure_for_approved_request(session, dsr)

            assert expected_reason in exc_info.value.reason_code

    run_async(_run())
