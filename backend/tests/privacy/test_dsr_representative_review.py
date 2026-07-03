from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditEvent
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


async def _create_representative_request(session):
    requester = await _create_user(session, email=f"rep-{uuid4()}@example.com")
    subject = await _create_user(session, email=f"subject-{uuid4()}@example.com")
    service = DataSubjectRequestService(session)
    request = await service.submit_request(
        requester_user_id=requester.id,
        subject_user_id=subject.id,
        request_type="export",
        requester_role=DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value,
        representative_relationship="parent",
        representative_authority_note="Authority evidence checked offline.",
        audit_context=AuditContext(actor_user_id=requester.id),
    )
    return service, requester, subject, request


def test_representative_submission_rejects_unknown_subject(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            requester = await _create_user(session, email="rep-missing@example.com")
            service = DataSubjectRequestService(session)

            with pytest.raises(BadRequestError, match="subject user was not found"):
                await service.submit_request(
                    requester_user_id=requester.id,
                    subject_user_id=uuid4(),
                    request_type="export",
                    requester_role=(
                        DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
                    ),
                    representative_relationship="parent",
                    representative_authority_note="Authority evidence checked offline.",
                    audit_context=AuditContext(actor_user_id=requester.id),
                )

    run_async(_run())


def test_verify_representative_authority_allows_approval(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            service, _, _, request = await _create_representative_request(session)
            reviewer = await _create_user(session, email="rep-reviewer@example.com")

            verified = await service.verify_representative_authority(
                request_id=request.id,
                reviewer_user_id=reviewer.id,
                reason_code="compliance_review",
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )

            assert verified.representative_status == (
                DataSubjectRequestRepresentativeStatus.VERIFIED.value
            )
            assert verified.representative_verified_by_user_id == reviewer.id
            assert verified.representative_verified_at is not None
            assert verified.representative_rejection_reason_code is None

            approved = await service.approve_request(
                request_id=request.id,
                reviewer_user_id=reviewer.id,
                reason_code="compliance_review",
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )
            assert approved.status == DataSubjectRequestStatus.APPROVED.value

    run_async(_run())


def test_reject_representative_authority_blocks_approval(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            service, _, _, request = await _create_representative_request(session)
            reviewer = await _create_user(session, email="rep-rejecter@example.com")

            rejected = await service.reject_representative_authority(
                request_id=request.id,
                reviewer_user_id=reviewer.id,
                reason_code="policy_violation",
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )

            assert rejected.representative_status == (
                DataSubjectRequestRepresentativeStatus.REJECTED.value
            )
            assert rejected.representative_rejection_reason_code == "policy_violation"
            assert rejected.representative_verified_by_user_id is None

            with pytest.raises(ConflictError, match="representative authority"):
                await service.approve_request(
                    request_id=request.id,
                    reviewer_user_id=reviewer.id,
                    reason_code="compliance_review",
                    audit_context=AuditContext(actor_user_id=reviewer.id),
                )

    run_async(_run())


def test_representative_authority_review_is_blocked_after_approval(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            service, _, _, request = await _create_representative_request(session)
            reviewer = await _create_user(session, email="rep-terminal@example.com")
            await service.verify_representative_authority(
                request_id=request.id,
                reviewer_user_id=reviewer.id,
                reason_code="compliance_review",
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )
            await service.approve_request(
                request_id=request.id,
                reviewer_user_id=reviewer.id,
                reason_code="compliance_review",
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )

            with pytest.raises(ConflictError, match="cannot be changed"):
                await service.reject_representative_authority(
                    request_id=request.id,
                    reviewer_user_id=reviewer.id,
                    reason_code="policy_violation",
                    audit_context=AuditContext(actor_user_id=reviewer.id),
                )

    run_async(_run())


def test_representative_authority_review_emits_minimal_audit(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            service, _, _, request = await _create_representative_request(session)
            reviewer = await _create_user(session, email="rep-audit@example.com")

            await service.verify_representative_authority(
                request_id=request.id,
                reviewer_user_id=reviewer.id,
                reason_code="compliance_review",
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )

            representative_verified_action = (
                AuditAction.DATA_SUBJECT_REQUEST_REPRESENTATIVE_VERIFIED.value
            )

            audit_row = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.target_id == request.id,
                        AuditEvent.action == representative_verified_action,
                    )
                )
            ).scalar_one()
            metadata = audit_row.metadata_json or {}
            assert metadata["request_type"] == "export"
            assert metadata["representative_status"] == "verified"
            assert "Authority evidence" not in str(metadata)

    run_async(_run())


def test_verifier_only_dsr_rows_are_exported_as_references(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            service, _, _, request = await _create_representative_request(session)
            verifier = await _create_user(session, email="verifier-export@example.com")
            await service.verify_representative_authority(
                request_id=request.id,
                reviewer_user_id=verifier.id,
                reason_code="compliance_review",
                audit_context=AuditContext(actor_user_id=verifier.id),
            )

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=request.id,
                    subject_user_id=verifier.id,
                    requester_user_id=verifier.id,
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
            assert matching[0]["record_kind"] == "reference"
            assert matching[0]["payload"]["representative_verified_by_user_id"] == (
                str(verifier.id)
            )
            assert "subject_user_id" in matching[0]["redacted_fields"]
            assert "requester_user_id" in matching[0]["redacted_fields"]

    run_async(_run())
