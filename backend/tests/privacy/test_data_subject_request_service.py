from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditEvent
from app.core.errors import ConflictError
from app.privacy.models.data_subject_request import DataSubjectRequestStatus
from app.privacy.services.data_subject_requests import DataSubjectRequestService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_user(session, *, email: str = "subject@example.com") -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email,
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def test_submit_request_calculates_due_and_self_subject(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            service = DataSubjectRequestService(session)
            now = datetime.now(UTC)
            request = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                requester_note="please export",
                idempotency_key="stable-key",
                now=now,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            assert request.requester_user_id == user.id
            assert request.subject_user_id == user.id
            assert request.status == DataSubjectRequestStatus.SUBMITTED.value
            expected_due = now + timedelta(days=service.DEFAULT_DUE_DAYS)
            assert request.due_at.replace(tzinfo=UTC) == expected_due

    run_async(_run())


def test_idempotency_returns_existing_or_conflict(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="idempotency@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            first = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                requester_note="note-a",
                idempotency_key="same-key",
                audit_context=audit_context,
            )
            second = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                requester_note="note-a",
                idempotency_key="same-key",
                audit_context=audit_context,
            )
            assert first.id == second.id

            with pytest.raises(ConflictError):
                await service.submit_request(
                    requester_user_id=user.id,
                    request_type="erase",
                    requester_note="note-b",
                    idempotency_key="same-key",
                    audit_context=audit_context,
                )

    run_async(_run())


def test_state_machine_and_terminal_protection(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="transition@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)
            request = await service.submit_request(
                requester_user_id=user.id,
                request_type="access",
                audit_context=audit_context,
            )
            request = await service.transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.UNDER_REVIEW,
                reviewer_user_id=user.id,
                audit_context=audit_context,
            )
            assert request.status == DataSubjectRequestStatus.UNDER_REVIEW.value
            request = await service.transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.APPROVED,
                reviewer_user_id=user.id,
                audit_context=audit_context,
            )
            request = await service.transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.FULFILLED,
                reviewer_user_id=user.id,
                audit_context=audit_context,
            )
            assert request.status == DataSubjectRequestStatus.FULFILLED.value
            with pytest.raises(ConflictError):
                await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.CANCELLED,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )

    run_async(_run())


def test_audit_metadata_is_minimal(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="audit@example.com")
            service = DataSubjectRequestService(session)
            note = "sensitive note"
            request = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                requester_note=note,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            rows = list(
                (
                    await session.execute(
                        select(AuditEvent).where(
                            AuditEvent.target_id == request.id,
                            AuditEvent.action
                            == AuditAction.DATA_SUBJECT_REQUEST_SUBMITTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            metadata = rows[0].metadata_json or {}
            assert metadata["request_type"] == "export"
            assert metadata["status"] == "submitted"
            assert note not in str(metadata)

    run_async(_run())
