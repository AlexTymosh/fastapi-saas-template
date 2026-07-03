from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.errors import BadRequestError, ConflictError
from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.subject_data import CrossTableSubjectDataExporter
from app.privacy.models.data_subject_request import (
    DataSubjectRequestRepresentativeStatus,
    DataSubjectRequestRequesterRole,
    DataSubjectRequestStatus,
)
from app.privacy.services.data_subject_requests import DataSubjectRequestService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_user(session, *, email: str) -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email,
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def test_self_service_submission_defaults_to_self_role(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="self-dsr@example.com")
            service = DataSubjectRequestService(session)

            request = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                audit_context=AuditContext(actor_user_id=user.id),
            )

            assert request.requester_user_id == user.id
            assert request.subject_user_id == user.id
            assert request.requester_role == DataSubjectRequestRequesterRole.SELF.value
            assert (
                request.representative_status
                == DataSubjectRequestRepresentativeStatus.NOT_REQUIRED.value
            )
            assert request.representative_relationship is None
            assert request.representative_authority_note is None

    run_async(_run())


def test_representative_submission_is_pending_verification(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            requester = await _create_user(session, email="representative@example.com")
            subject = await _create_user(session, email="represented@example.com")
            service = DataSubjectRequestService(session)

            request = await service.submit_request(
                requester_user_id=requester.id,
                subject_user_id=subject.id,
                request_type="export",
                requester_role=(
                    DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                ),
                representative_relationship="parent",
                representative_authority_note="Authority evidence is held offline.",
                audit_context=AuditContext(actor_user_id=requester.id),
            )

            assert request.requester_user_id == requester.id
            assert request.subject_user_id == subject.id
            assert request.requester_role == (
                DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
            )
            assert request.representative_status == (
                DataSubjectRequestRepresentativeStatus.PENDING_VERIFICATION.value
            )
            assert request.representative_relationship == "parent"
            assert (
                request.representative_authority_note
                == "Authority evidence is held offline."
            )

    run_async(_run())


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"subject_user_id": uuid4(), "representative_relationship": "parent"},
        {"subject_user_id": uuid4(), "representative_authority_note": "note"},
    ],
)
def test_representative_submission_requires_authority_details(
    migrated_session_factory,
    kwargs: dict[str, object],
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            requester = await _create_user(
                session, email="missing-representative@example.com"
            )
            service = DataSubjectRequestService(session)

            with pytest.raises(BadRequestError):
                await service.submit_request(
                    requester_user_id=requester.id,
                    request_type="export",
                    requester_role=(
                        DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                    ),
                    audit_context=AuditContext(actor_user_id=requester.id),
                    **kwargs,
                )

    run_async(_run())


def test_representative_submission_blocks_approval_until_verified(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            reviewer = await _create_user(session, email="reviewer@example.com")
            requester = await _create_user(session, email="rep-approval@example.com")
            subject = await _create_user(session, email="subject-approval@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=reviewer.id)

            request = await service.submit_request(
                requester_user_id=requester.id,
                subject_user_id=subject.id,
                request_type="export",
                requester_role=(
                    DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                ),
                representative_relationship="parent",
                representative_authority_note="Authority evidence is held offline.",
                audit_context=AuditContext(actor_user_id=requester.id),
            )

            with pytest.raises(ConflictError, match="representative authority"):
                await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.APPROVED,
                    reviewer_user_id=reviewer.id,
                    audit_context=audit_context,
                )

            request.representative_status = (
                DataSubjectRequestRepresentativeStatus.VERIFIED.value
            )
            await service.repository.save(request)

            approved = await service.transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.APPROVED,
                reviewer_user_id=reviewer.id,
                audit_context=audit_context,
            )

            assert approved.status == DataSubjectRequestStatus.APPROVED.value

    run_async(_run())


def test_representative_idempotency_fingerprint_includes_subject(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            requester = await _create_user(session, email="rep-idem@example.com")
            subject_a = await _create_user(session, email="subject-a@example.com")
            subject_b = await _create_user(session, email="subject-b@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=requester.id)

            first = await service.submit_request(
                requester_user_id=requester.id,
                subject_user_id=subject_a.id,
                request_type="export",
                requester_role=(
                    DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                ),
                representative_relationship="parent",
                representative_authority_note="same note",
                idempotency_key="representative-key",
                audit_context=audit_context,
            )
            second = await service.submit_request(
                requester_user_id=requester.id,
                subject_user_id=subject_a.id,
                request_type="export",
                requester_role=(
                    DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                ),
                representative_relationship="parent",
                representative_authority_note="same note",
                idempotency_key="representative-key",
                audit_context=audit_context,
            )
            assert first.id == second.id

            with pytest.raises(ConflictError):
                await service.submit_request(
                    requester_user_id=requester.id,
                    subject_user_id=subject_b.id,
                    request_type="export",
                    requester_role=(
                        DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                    ),
                    representative_relationship="parent",
                    representative_authority_note="same note",
                    idempotency_key="representative-key",
                    audit_context=audit_context,
                )

    run_async(_run())


def test_representative_export_record_redacts_other_subject_id(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            requester = await _create_user(session, email="rep-export@example.com")
            subject = await _create_user(session, email="subject-export@example.com")
            service = DataSubjectRequestService(session)
            request = await service.submit_request(
                requester_user_id=requester.id,
                subject_user_id=subject.id,
                request_type="export",
                requester_role=(
                    DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                ),
                representative_relationship="parent",
                representative_authority_note="Authority evidence is held offline.",
                audit_context=AuditContext(actor_user_id=requester.id),
            )
            await session.flush()

            exporter = CrossTableSubjectDataExporter(session)
            payload = await exporter.export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=request.id,
                    subject_user_id=requester.id,
                    requester_user_id=requester.id,
                    request_type="export",
                    request_status="approved",
                    generated_at=datetime.now(UTC),
                    schema_version="1.0",
                )
            )
            dsr_records = payload["data"]["dsr.workflow_records"]
            matching = [
                record
                for record in dsr_records
                if record["payload"].get("id") == str(request.id)
            ]

            assert len(matching) == 1
            record = matching[0]
            assert record["payload"]["requester_user_id"] == str(requester.id)
            assert record["payload"]["has_subject"] is True
            assert "subject_user_id" not in record["payload"]
            assert "subject_user_id" in record["redacted_fields"]

    run_async(_run())
