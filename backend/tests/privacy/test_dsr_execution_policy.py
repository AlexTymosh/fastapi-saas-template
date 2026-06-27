from __future__ import annotations

from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.errors import ConflictError
from app.privacy.models.data_subject_request import (
    DataSubjectRequestStatus,
    DataSubjectRequestType,
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


@pytest.mark.parametrize(
    "request_type",
    [
        DataSubjectRequestType.ACCESS,
        DataSubjectRequestType.RECTIFY,
        DataSubjectRequestType.RESTRICT,
        DataSubjectRequestType.OBJECT,
        DataSubjectRequestType.PORTABILITY,
    ],
)
def test_request_types_without_execution_policy_cannot_be_approved(
    migrated_session_factory,
    request_type: DataSubjectRequestType,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(
                session,
                email=f"unsupported-{request_type.value}@example.com",
            )
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)
            request = await service.submit_request(
                requester_user_id=user.id,
                request_type=request_type.value,
                audit_context=audit_context,
            )

            reviewed = await service.mark_under_review(
                request_id=request.id,
                reviewer_user_id=user.id,
                audit_context=audit_context,
            )
            assert reviewed.status == DataSubjectRequestStatus.UNDER_REVIEW.value

            with pytest.raises(ConflictError, match="no execution policy"):
                await service.approve_request(
                    request_id=request.id,
                    reviewer_user_id=user.id,
                    reason_code="compliance_review",
                    audit_context=audit_context,
                )

            persisted = await service.get_request(request_id=request.id)
            assert persisted.status == DataSubjectRequestStatus.UNDER_REVIEW.value
            assert persisted.decided_at is None
            assert persisted.decision_reason_code is None

            rejected = await service.reject_request(
                request_id=request.id,
                reviewer_user_id=user.id,
                reason_code="unsupported_request_type",
                audit_context=audit_context,
            )
            assert rejected.status == DataSubjectRequestStatus.REJECTED.value
            assert rejected.rejection_reason_code == "unsupported_request_type"

    run_async(_run())


def test_export_and_erase_request_types_remain_approvable(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="approvable-dsr@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            for request_type in (
                DataSubjectRequestType.EXPORT,
                DataSubjectRequestType.ERASE,
            ):
                request = await service.submit_request(
                    requester_user_id=user.id,
                    request_type=request_type.value,
                    audit_context=audit_context,
                )
                approved = await service.approve_request(
                    request_id=request.id,
                    reviewer_user_id=user.id,
                    reason_code="compliance_review",
                    audit_context=audit_context,
                )
                assert approved.status == DataSubjectRequestStatus.APPROVED.value
                assert approved.decision_reason_code == "compliance_review"

    run_async(_run())
