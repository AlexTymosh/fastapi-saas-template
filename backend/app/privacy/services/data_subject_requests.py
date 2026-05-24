from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors import ConflictError, NotFoundError
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.privacy.repositories.data_subject_requests import DataSubjectRequestRepository


class DataSubjectRequestService:
    DEFAULT_DUE_DAYS = 30
    EXTENSION_DAYS = 60
    MAX_DUE_DAYS = 90
    IDEMPOTENCY_KEY_TTL_HOURS = 24

    _ALLOWED_TRANSITIONS = {
        DataSubjectRequestStatus.SUBMITTED.value: {
            DataSubjectRequestStatus.UNDER_REVIEW.value,
            DataSubjectRequestStatus.APPROVED.value,
            DataSubjectRequestStatus.FULFILLED.value,
            DataSubjectRequestStatus.CANCELLED.value,
        },
        DataSubjectRequestStatus.UNDER_REVIEW.value: {
            DataSubjectRequestStatus.APPROVED.value,
            DataSubjectRequestStatus.REJECTED.value,
            DataSubjectRequestStatus.CANCELLED.value,
        },
        DataSubjectRequestStatus.APPROVED.value: {
            DataSubjectRequestStatus.FULFILLED.value,
            DataSubjectRequestStatus.CANCELLED.value,
        },
    }

    def __init__(self, session: AsyncSession) -> None:
        self.repository = DataSubjectRequestRepository(session)
        self.audit_events = AuditEventService(session)

    async def submit_request(
        self,
        *,
        requester_user_id: UUID,
        request_type: str,
        requester_note: str | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
        audit_context: AuditContext,
    ) -> DataSubjectRequest:
        reference_now = now or datetime.now(UTC)
        idempotency_key_hash = (
            self._hash_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else None
        )
        idempotency_fingerprint = (
            self._build_fingerprint(
                request_type=request_type,
                requester_note=requester_note,
            )
            if idempotency_key_hash is not None
            else None
        )

        if idempotency_key_hash is not None:
            existing = await self.repository.get_non_expired_by_idempotency_key_hash(
                requester_user_id=requester_user_id,
                idempotency_key_hash=idempotency_key_hash,
                now=reference_now,
            )
            if existing is not None:
                if existing.idempotency_fingerprint == idempotency_fingerprint:
                    return existing
                raise ConflictError(
                    detail=(
                        "Idempotency key is already used for another request payload"
                    )
                )

        request = await self.repository.create(
            request_type=request_type,
            status=DataSubjectRequestStatus.SUBMITTED.value,
            requester_user_id=requester_user_id,
            subject_user_id=requester_user_id,
            requester_note=requester_note,
            submitted_at=reference_now,
            due_at=reference_now + timedelta(days=self.DEFAULT_DUE_DAYS),
            idempotency_key_hash=idempotency_key_hash,
            idempotency_fingerprint=idempotency_fingerprint,
            idempotency_key_expires_at=(
                reference_now + timedelta(hours=self.IDEMPOTENCY_KEY_TTL_HOURS)
                if idempotency_key_hash is not None
                else None
            ),
        )

        await self._record_status_event(
            request=request,
            action=AuditAction.DATA_SUBJECT_REQUEST_SUBMITTED,
            audit_context=audit_context,
        )
        return request

    async def get_request(self, *, request_id: UUID) -> DataSubjectRequest:
        request = await self.repository.get_by_id(request_id)
        if request is None:
            raise NotFoundError(detail="Data subject request not found")
        return request

    async def transition_status(
        self,
        *,
        request_id: UUID,
        target_status: DataSubjectRequestStatus,
        reviewer_user_id: UUID | None,
        audit_context: AuditContext,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> DataSubjectRequest:
        reference_now = now or datetime.now(UTC)
        request = await self.get_request(request_id=request_id)
        current_status = request.status
        next_status = target_status.value

        allowed = self._ALLOWED_TRANSITIONS.get(current_status, set())
        if next_status not in allowed:
            raise ConflictError(
                detail=f"Invalid transition from '{current_status}' to '{next_status}'"
            )

        request.status = next_status
        request.reviewer_user_id = reviewer_user_id

        if next_status == DataSubjectRequestStatus.UNDER_REVIEW.value:
            request.reviewed_at = reference_now
        if next_status in {
            DataSubjectRequestStatus.APPROVED.value,
            DataSubjectRequestStatus.REJECTED.value,
        }:
            request.decided_at = reference_now
        if next_status == DataSubjectRequestStatus.FULFILLED.value:
            request.fulfilled_at = reference_now
        if next_status == DataSubjectRequestStatus.CANCELLED.value:
            request.cancelled_at = reference_now
        if next_status == DataSubjectRequestStatus.REJECTED.value:
            request.rejection_reason_code = reason_code
        if next_status == DataSubjectRequestStatus.APPROVED.value:
            request.decision_reason_code = reason_code

        saved = await self.repository.save(request)
        persisted_request = saved or request

        await self._record_status_event(
            request=persisted_request,
            action=self._action_for_status(target_status),
            audit_context=audit_context,
        )
        return persisted_request

    @staticmethod
    def _hash_idempotency_key(key: str) -> str:
        return sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_fingerprint(*, request_type: str, requester_note: str | None) -> str:
        fingerprint_source = (
            f"request_type={request_type}|requester_note={requester_note or ''}"
        )
        return sha256(fingerprint_source.encode("utf-8")).hexdigest()

    @staticmethod
    def _action_for_status(status: DataSubjectRequestStatus) -> AuditAction:
        mapping = {
            DataSubjectRequestStatus.UNDER_REVIEW: (
                AuditAction.DATA_SUBJECT_REQUEST_UNDER_REVIEW
            ),
            DataSubjectRequestStatus.APPROVED: (
                AuditAction.DATA_SUBJECT_REQUEST_APPROVED
            ),
            DataSubjectRequestStatus.REJECTED: (
                AuditAction.DATA_SUBJECT_REQUEST_REJECTED
            ),
            DataSubjectRequestStatus.CANCELLED: (
                AuditAction.DATA_SUBJECT_REQUEST_CANCELLED
            ),
            DataSubjectRequestStatus.FULFILLED: (
                AuditAction.DATA_SUBJECT_REQUEST_FULFILLED
            ),
        }
        return mapping[status]

    async def _record_status_event(
        self,
        *,
        request: DataSubjectRequest,
        action: AuditAction,
        audit_context: AuditContext,
    ) -> None:
        await self.audit_events.record_event(
            audit_context=audit_context,
            category=AuditCategory.COMPLIANCE,
            action=action,
            target_type=AuditTargetType.DATA_SUBJECT_REQUEST,
            target_id=request.id,
            metadata_json={
                "request_type": request.request_type,
                "status": request.status,
            },
        )
