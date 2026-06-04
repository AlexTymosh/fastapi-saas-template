from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
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


async def _create_user(session, *, email: str | None = None) -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email or f"subject-{uuid4()}@example.com",
        email_verified=True,
        first_name="Subject",
        last_name="User",
        onboarding_completed=True,
        suspended_reason="Free-text note that may contain personal data",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_organisation(session) -> Organisation:
    organisation = Organisation(
        name="Privacy Test Organisation",
        slug=f"privacy-test-{uuid4()}",
    )
    session.add(organisation)
    await session.flush()
    await session.refresh(organisation)
    return organisation


def _dsr_for_user(
    user: User,
    *,
    request_type: str = "erase",
    status: str = DataSubjectRequestStatus.APPROVED.value,
    execution_status: str = DataSubjectRequestExecutionStatus.NOT_STARTED.value,
) -> DataSubjectRequest:
    now = datetime.now(UTC)
    return DataSubjectRequest(
        request_type=request_type,
        status=status,
        execution_status=execution_status,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=now,
        reviewed_at=now if status == DataSubjectRequestStatus.APPROVED.value else None,
        decided_at=now if status == DataSubjectRequestStatus.APPROVED.value else None,
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


async def _create_subject_invite(
    session,
    *,
    subject_email: str,
    organisation_id: UUID,
) -> Invite:
    invite = Invite(
        email=subject_email,
        organisation_id=organisation_id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.PENDING,
        token_hash=f"token-{uuid4()}",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(invite)
    await session.flush()
    await session.refresh(invite)
    return invite


def test_core_erasure_orchestrator_runs_providers_in_safe_order(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"Subject-{uuid4()}@Example.COM"
            user = await _create_user(session, email=subject_email)
            organisation = await _create_organisation(session)
            invite = await _create_subject_invite(
                session,
                subject_email=subject_email.lower(),
                organisation_id=organisation.id,
            )
            dsr = _dsr_for_user(user)
            outbox_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json=_invite_payload(
                    invite_id=invite.id,
                    email=subject_email.lower(),
                ),
                status=OutboxStatus.PENDING.value,
            )
            session.add_all([dsr, outbox_event])
            await session.flush()

            result = await execute_core_erasure_for_approved_request(session, dsr)
            await session.refresh(dsr)
            await session.refresh(user)
            await session.refresh(invite)
            await session.refresh(outbox_event)

            assert result.status is ErasureOrchestrationStatus.COMPLETED
            assert result.provider_keys == (
                "outbox.purge_or_scrub_payload",
                "invites.anonymise_or_purge_subject_references",
                "users.anonymise_profile",
            )
            assert result.affected_rows == 3
            assert dsr.execution_status == DataSubjectRequestExecutionStatus.READY.value
            assert dsr.execution_started_at is not None
            assert dsr.execution_completed_at is not None
            assert dsr.execution_failed_at is None
            assert dsr.execution_failure_reason_code is None

            assert user.email is None
            assert user.external_auth_id == f"erased-user:{user.id}"
            assert invite.email.endswith("@anonymous.invalid")
            assert invite.status == InviteStatus.REVOKED
            assert outbox_event.status == OutboxStatus.FAILED.value
            assert "email" not in outbox_event.payload_json
            assert "encrypted_raw_token" not in outbox_event.payload_json

    run_async(_run())


def test_core_erasure_orchestrator_rolls_back_on_processing_outbox(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"processing-{uuid4()}@example.com"
            user = await _create_user(session, email=subject_email)
            organisation = await _create_organisation(session)
            invite = await _create_subject_invite(
                session,
                subject_email=subject_email,
                organisation_id=organisation.id,
            )
            dsr = _dsr_for_user(user)
            processing_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json=_invite_payload(invite_id=invite.id, email=subject_email),
                status=OutboxStatus.PROCESSING.value,
                locked_at=datetime.now(UTC),
            )
            session.add_all([dsr, processing_event])
            await session.flush()

            with pytest.raises(ErasureOrchestrationError) as exc_info:
                await execute_core_erasure_for_approved_request(session, dsr)

            assert "processing_rows_in_flight" in exc_info.value.reason_code
            await session.refresh(dsr)
            await session.refresh(user)
            await session.refresh(invite)
            await session.refresh(processing_event)

            assert dsr.execution_status == (
                DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert dsr.execution_failure_reason_code == (
                "outbox_erasure_processing_rows_in_flight"
            )
            assert user.email == subject_email
            assert user.external_auth_id.startswith("kc|")
            assert invite.email == subject_email
            assert invite.token_hash.startswith("token-")
            assert processing_event.status == OutboxStatus.PROCESSING.value
            assert processing_event.payload_json["email"] == subject_email
            assert processing_event.payload_json["encrypted_raw_token"]

    run_async(_run())


def test_core_erasure_orchestrator_is_idempotent_when_ready(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(
                user,
                execution_status=DataSubjectRequestExecutionStatus.READY.value,
            )
            session.add(dsr)
            await session.flush()

            result = await execute_core_erasure_for_approved_request(session, dsr)

            assert result.status is ErasureOrchestrationStatus.ALREADY_COMPLETED
            assert result.provider_results == ()
            assert result.affected_rows == 0
            await session.refresh(user)
            assert user.email is not None

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
            await session.refresh(user)
            assert user.email is not None

    run_async(_run())
