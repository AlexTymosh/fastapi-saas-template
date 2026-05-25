from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.repositories.data_subject_requests import DataSubjectRequestRepository


class DataSubjectRequestService:
    DEFAULT_DUE_DAYS = 30
    EXTENSION_DAYS = 60
    MAX_DUE_DAYS = 90
    IDEMPOTENCY_KEY_TTL_HOURS = 24
    REQUESTER_NOTE_MAX_LENGTH = 2000

    _EMAIL_LIKE_PATTERN = re.compile(
        r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
        re.IGNORECASE,
    )
    _UNSAFE_IDEMPOTENCY_PATTERNS = (
        re.compile(r"^\s*bearer\s+[A-Z0-9._\-+/=]+", re.IGNORECASE),
        re.compile(r"^\s*basic\s+[A-Z0-9._\-+/=]+", re.IGNORECASE),
        re.compile(
            r"(api[_\-]?key|secret|password|passwd|token)\s*[:=]", re.IGNORECASE
        ),
        re.compile(r"eyJ[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+"),
        re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}", re.IGNORECASE),
    )

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
        normalised_request_type = self._normalise_request_type(request_type)
        normalised_idempotency_key = self._normalise_idempotency_key(idempotency_key)

        if (
            requester_note is not None
            and len(requester_note) > self.REQUESTER_NOTE_MAX_LENGTH
        ):
            raise BadRequestError(
                detail=(
                    "Requester note exceeds maximum length of "
                    f"{self.REQUESTER_NOTE_MAX_LENGTH} characters"
                )
            )

        self._validate_idempotency_key_safety(
            idempotency_key=normalised_idempotency_key
        )
        idempotency_key_hash = (
            self._hash_idempotency_key(normalised_idempotency_key)
            if normalised_idempotency_key is not None
            else None
        )
        idempotency_fingerprint = (
            self._build_fingerprint(
                request_type=normalised_request_type,
                requester_note=requester_note,
            )
            if idempotency_key_hash is not None
            else None
        )

        if idempotency_key_hash is not None:
            await self.repository.lock_requester_for_idempotency(
                requester_user_id=requester_user_id,
            )
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
            request_type=normalised_request_type,
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

    async def list_own_requests(
        self,
        *,
        requester_user_id: UUID,
        limit: int,
        offset: int,
        status: str | None = None,
        request_type: str | None = None,
    ) -> tuple[list[DataSubjectRequest], int]:
        rows = await self.repository.list_for_requester(
            requester_user_id=requester_user_id,
            limit=limit,
            offset=offset,
            status=status,
            request_type=request_type,
        )
        total = await self.repository.count_for_requester(
            requester_user_id=requester_user_id,
            status=status,
            request_type=request_type,
        )
        return rows, total

    async def get_own_request(
        self, *, requester_user_id: UUID, request_id: UUID
    ) -> DataSubjectRequest:
        row = await self.repository.get_by_id_for_requester(
            request_id=request_id, requester_user_id=requester_user_id
        )
        if row is None:
            raise NotFoundError(detail="Data subject request not found")
        return row

    async def cancel_own_request(
        self, *, requester_user_id: UUID, request_id: UUID, audit_context: AuditContext
    ) -> DataSubjectRequest:
        request = await self.get_own_request(
            requester_user_id=requester_user_id, request_id=request_id
        )
        if request.status not in {
            DataSubjectRequestStatus.SUBMITTED.value,
            DataSubjectRequestStatus.UNDER_REVIEW.value,
        }:
            raise ConflictError(detail="Request cannot be cancelled in current state")
        return await self.transition_status(
            request_id=request_id,
            target_status=DataSubjectRequestStatus.CANCELLED,
            reviewer_user_id=requester_user_id,
            audit_context=audit_context,
        )

    async def list_platform_requests(
        self, **kwargs
    ) -> tuple[list[DataSubjectRequest], int]:
        rows = await self.repository.list_for_platform(**kwargs)
        total = await self.repository.count_for_platform(
            status=kwargs.get("status"),
            request_type=kwargs.get("request_type"),
            subject_user_id=kwargs.get("subject_user_id"),
            requester_user_id=kwargs.get("requester_user_id"),
            due_before=kwargs.get("due_before"),
            due_after=kwargs.get("due_after"),
        )
        return rows, total

    async def get_platform_request(self, *, request_id: UUID) -> DataSubjectRequest:
        return await self.get_request(request_id=request_id)

    async def mark_under_review(
        self, *, request_id: UUID, reviewer_user_id: UUID, audit_context: AuditContext
    ) -> DataSubjectRequest:
        return await self.transition_status(
            request_id=request_id,
            target_status=DataSubjectRequestStatus.UNDER_REVIEW,
            reviewer_user_id=reviewer_user_id,
            audit_context=audit_context,
        )

    async def approve_request(
        self,
        *,
        request_id: UUID,
        reviewer_user_id: UUID,
        reason_code: str | None,
        audit_context: AuditContext,
    ) -> DataSubjectRequest:
        return await self.transition_status(
            request_id=request_id,
            target_status=DataSubjectRequestStatus.APPROVED,
            reviewer_user_id=reviewer_user_id,
            reason_code=reason_code,
            audit_context=audit_context,
        )

    async def reject_request(
        self,
        *,
        request_id: UUID,
        reviewer_user_id: UUID,
        reason_code: str,
        audit_context: AuditContext,
    ) -> DataSubjectRequest:
        return await self.transition_status(
            request_id=request_id,
            target_status=DataSubjectRequestStatus.REJECTED,
            reviewer_user_id=reviewer_user_id,
            reason_code=reason_code,
            audit_context=audit_context,
        )

    async def cancel_platform_request(
        self,
        *,
        request_id: UUID,
        reviewer_user_id: UUID,
        audit_context: AuditContext,
    ) -> DataSubjectRequest:
        return await self.transition_status(
            request_id=request_id,
            target_status=DataSubjectRequestStatus.CANCELLED,
            reviewer_user_id=reviewer_user_id,
            audit_context=audit_context,
        )

    async def fulfil_request(
        self, *, request_id: UUID, reviewer_user_id: UUID, audit_context: AuditContext
    ) -> DataSubjectRequest:
        request = await self.get_request(request_id=request_id)
        if request.status != DataSubjectRequestStatus.APPROVED.value:
            raise ConflictError(detail="Only approved requests can be fulfilled")
        return await self.transition_status(
            request_id=request_id,
            target_status=DataSubjectRequestStatus.FULFILLED,
            reviewer_user_id=reviewer_user_id,
            audit_context=audit_context,
        )

    @staticmethod
    def _normalise_idempotency_key(key: str | None) -> str | None:
        if key is None:
            return None
        return key.strip()

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
    def _normalise_request_type(request_type: str) -> str:
        try:
            return DataSubjectRequestType(request_type).value
        except ValueError as exc:
            raise BadRequestError(
                detail=(
                    "Invalid request_type. Supported values: "
                    "access, export, erase, rectify, restrict, object, portability"
                )
            ) from exc

    @classmethod
    def _validate_idempotency_key_safety(cls, *, idempotency_key: str | None) -> None:
        if idempotency_key is None:
            return
        candidate = idempotency_key.strip()
        if not candidate:
            raise BadRequestError(detail="Idempotency key must not be empty")
        if len(candidate) > 512:
            raise BadRequestError(detail="Idempotency key is too long")
        if cls._EMAIL_LIKE_PATTERN.search(candidate):
            raise BadRequestError(
                detail="Idempotency key must not contain email-like values"
            )
        for pattern in cls._UNSAFE_IDEMPOTENCY_PATTERNS:
            if pattern.search(candidate):
                raise BadRequestError(
                    detail=(
                        "Idempotency key appears to contain credential "
                        "or token-like content"
                    )
                )
        # Guard against obvious key-value blobs often copied from headers.
        if ":" in candidate and "=" in candidate:
            raise BadRequestError(
                detail=("Idempotency key appears to contain sensitive structured data")
            )

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
