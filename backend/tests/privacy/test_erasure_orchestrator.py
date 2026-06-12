from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
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
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.models.privacy_governance import (
    ConsentRecord,
    DataProcessingAuthorization,
    LawfulBasis,
    PrivacyNoticeAcceptance,
    ProcessingPurpose,
    ProcessingPurposeFamily,
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


def _organisation() -> Organisation:
    return Organisation(name=f"Organisation {uuid4()}", slug=f"org-{uuid4()}")


def _membership(user: User, organisation: Organisation) -> Membership:
    return Membership(
        user_id=user.id,
        organisation_id=organisation.id,
        role=MembershipRole.MEMBER,
        is_active=True,
    )


def _platform_staff_for_user(
    user: User,
    *,
    created_by_user_id: UUID | None = None,
) -> PlatformStaff:
    return PlatformStaff(
        user_id=user.id,
        role=PlatformStaffRole.SUPPORT_AGENT.value,
        status=PlatformStaffStatus.SUSPENDED.value,
        created_by_user_id=created_by_user_id,
        suspended_reason="subject-linked free text",
    )


def _export_artifact(dsr: DataSubjectRequest, user: User) -> ExportArtifact:
    now = datetime.now(UTC)
    return ExportArtifact(
        data_subject_request_id=dsr.id,
        subject_user_id=user.id,
        requester_user_id=user.id,
        requested_by_user_id=user.id,
        generated_by_user_id=user.id,
        status=ExportArtifactStatus.FAILED.value,
        format=ExportArtifactFormat.JSON_ZIP.value,
        storage_backend=ExportArtifactStorageBackend.LOCAL.value,
        storage_key="privacy-exports/object.zip",
        filename="subject.zip",
        content_type="application/zip",
        schema_version="1.0",
        failure_reason_code="worker_failed",
        failure_detail="subject-linked failure detail",
        processing_token="worker-token",
        processing_lease_expires_at=now + timedelta(minutes=5),
        queued_at=now,
        expires_at=now + timedelta(days=30),
    )


def _processing_purpose() -> ProcessingPurpose:
    return ProcessingPurpose(
        code=f"privacy-purpose-{uuid4()}",
        title="Privacy purpose",
        family=ProcessingPurposeFamily.LEGAL_COMPLIANCE.value,
        default_lawful_basis=LawfulBasis.LEGAL_OBLIGATION.value,
        active=True,
    )


def _authorization(
    user: User,
    purpose: ProcessingPurpose,
) -> DataProcessingAuthorization:
    return DataProcessingAuthorization(
        subject_user_id=user.id,
        purpose_id=purpose.id,
        lawful_basis=LawfulBasis.LEGAL_OBLIGATION.value,
        active=True,
        valid_from=datetime.now(UTC),
        source="signup form",
    )


def _consent(user: User, purpose: ProcessingPurpose) -> ConsentRecord:
    return ConsentRecord(
        subject_user_id=user.id,
        purpose_id=purpose.id,
        privacy_notice_version="2026-06",
        withdrawal_reason_code="user_request",
    )


def _notice(user: User) -> PrivacyNoticeAcceptance:
    return PrivacyNoticeAcceptance(
        subject_user_id=user.id,
        notice_version="2026-06",
        source="web signup",
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


def _audit_event_for_user(user: User) -> AuditEvent:
    return AuditEvent(
        actor_user_id=user.id,
        category=AuditCategory.COMPLIANCE.value,
        action=AuditAction.DATA_SUBJECT_REQUEST_APPROVED.value,
        target_type=AuditTargetType.USER.value,
        target_id=user.id,
        reason="free text about subject",
        metadata_json={"email": user.email, "note": "subject context"},
        ip_address="198.51.100.25",
        user_agent="Subject user agent",
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
            audit_event = _audit_event_for_user(user)
            session.add_all([dsr, event, audit_event])
            await session.flush()

            result = await execute_core_erasure_for_approved_request(session, dsr)
            await session.refresh(dsr)
            await session.refresh(user)
            await session.refresh(event)
            await session.refresh(audit_event)

            assert result.status is ErasureOrchestrationStatus.COMPLETED
            assert result.failure_reason_code is None
            assert result.provider_keys == (
                "audit.minimise_subject_actor_or_target_identifiers",
                "outbox.purge_or_scrub_payload",
                "invites.anonymise_or_purge_subject_references",
                "memberships.minimise_subject_link",
                "organisations.review_subject_references",
                "platform_staff.minimise_subject_or_creator_links",
                "export_artifacts.delete_object_minimise_subject_or_actor_metadata",
                "privacy_governance.minimise_authorizations",
                "privacy_governance.minimise_consent_records",
                "privacy_governance.minimise_notice_acceptances",
                "users.anonymise_profile",
                "dsr.minimise_workflow_identifiers",
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
            assert audit_event.actor_user_id is None
            assert audit_event.target_id is None
            assert audit_event.reason is None
            assert audit_event.metadata_json is None
            assert audit_event.ip_address is None
            assert audit_event.user_agent is None

    run_async(_run())


def test_core_erasure_orchestrator_covers_remaining_inventory_targets(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"coverage-{uuid4()}@example.com"
            user = await _create_user(session, email=subject_email)
            creator = await _create_user(
                session,
                email=f"creator-{uuid4()}@example.com",
            )
            dsr = _dsr_for_user(user)
            organisation = _organisation()
            purpose = _processing_purpose()
            session.add_all([dsr, organisation, purpose])
            await session.flush()

            membership = _membership(user, organisation)
            platform_staff = _platform_staff_for_user(
                creator,
                created_by_user_id=user.id,
            )
            artifact = _export_artifact(dsr, user)
            authorization = _authorization(user, purpose)
            consent = _consent(user, purpose)
            notice = _notice(user)
            dsr.requester_note = "subject note"
            dsr.internal_note = "internal subject note"
            dsr.idempotency_key_hash = "idempotency-hash"
            dsr.idempotency_fingerprint = "idempotency-fingerprint"
            dsr.idempotency_key_expires_at = datetime.now(UTC) + timedelta(hours=1)
            session.add_all(
                [
                    membership,
                    platform_staff,
                    artifact,
                    authorization,
                    consent,
                    notice,
                ]
            )
            await session.flush()

            result = await execute_core_erasure_for_approved_request(session, dsr)
            await session.refresh(dsr)
            await session.refresh(user)
            await session.refresh(membership)
            await session.refresh(platform_staff)
            await session.refresh(artifact)
            await session.refresh(authorization)
            await session.refresh(consent)
            await session.refresh(notice)

            assert result.status is ErasureOrchestrationStatus.COMPLETED
            assert membership.user_id == user.id
            assert membership.organisation_id == organisation.id
            assert platform_staff.created_by_user_id is None
            assert platform_staff.suspended_reason is None
            assert artifact.subject_user_id is None
            assert artifact.requester_user_id is None
            assert artifact.requested_by_user_id is None
            assert artifact.generated_by_user_id is None
            assert artifact.failure_detail is None
            assert artifact.processing_token is None
            assert artifact.processing_lease_expires_at is None
            assert authorization.subject_user_id == user.id
            assert authorization.source is None
            assert consent.subject_user_id == user.id
            assert consent.withdrawal_reason_code == "user_request"
            assert notice.subject_user_id == user.id
            assert notice.source is None
            assert dsr.requester_user_id is None
            assert dsr.subject_user_id is None
            assert dsr.requester_note is None
            assert dsr.internal_note is None
            assert dsr.idempotency_key_hash is None
            assert dsr.idempotency_fingerprint is None
            assert dsr.idempotency_key_expires_at is None
            assert user.email is None

    run_async(_run())


def test_core_erasure_orchestrator_rolls_back_on_audit_legal_hold(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                subject_email = f"held-{uuid4()}@example.com"
                user = await _create_user(session, email=subject_email)
                dsr = _dsr_for_user(user)
                event = _outbox_event(invite_id=uuid4(), email=subject_email)
                audit_event = _audit_event_for_user(user)
                audit_event.legal_hold_until = datetime.now(UTC) + timedelta(days=7)
                session.add_all([dsr, event, audit_event])
                await session.flush()

                result = await execute_core_erasure_for_approved_request(
                    session,
                    dsr,
                )
                assert result.status is ErasureOrchestrationStatus.FAILED
                assert result.failure_reason_code == "audit_erasure_legal_hold_active"
                assert result.provider_results == ()

            await session.refresh(dsr)
            await session.refresh(user)
            await session.refresh(event)
            await session.refresh(audit_event)
            assert (
                dsr.execution_status == DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert dsr.execution_failure_reason_code == (
                "audit_erasure_legal_hold_active"
            )
            assert user.email == subject_email
            assert event.status == OutboxStatus.PENDING.value
            assert "email" in event.payload_json
            assert audit_event.actor_user_id == user.id
            assert audit_event.reason == "free text about subject"
            assert audit_event.metadata_json == {
                "email": subject_email,
                "note": "subject context",
            }

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


def test_core_erasure_orchestrator_is_idempotent_after_dsr_minimisation(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(user)
            session.add(dsr)
            await session.flush()

            first_result = await execute_core_erasure_for_approved_request(session, dsr)
            await session.refresh(dsr)

            assert first_result.status is ErasureOrchestrationStatus.COMPLETED
            assert dsr.execution_status == DataSubjectRequestExecutionStatus.READY.value
            assert dsr.subject_user_id is None

            second_result = await execute_core_erasure_for_approved_request(
                session,
                dsr,
            )
            await session.refresh(dsr)

            assert second_result.status is ErasureOrchestrationStatus.ALREADY_COMPLETED
            assert second_result.subject_user_id is None
            assert second_result.provider_results == ()
            assert second_result.did_mutate is False
            assert second_result.failure_reason_code is None
            assert dsr.execution_status == DataSubjectRequestExecutionStatus.READY.value
            assert dsr.execution_failure_reason_code is None

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
