from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.privacy.erasures.execution import (
    ErasureExecutionError,
    execute_approved_erasure_request_by_staff,
)
from app.privacy.erasures.orchestrator import ErasureOrchestrationError
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestRepresentativeStatus,
    DataSubjectRequestRequesterRole,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import ExportArtifact, ExportArtifactStatus
from app.privacy.repositories.data_subject_requests import DataSubjectRequestRepository
from app.privacy.repositories.export_artifacts import ExportArtifactRepository
from app.users.models.user import User

_FULFILMENT_PIPELINE_REQUEST_TYPES = frozenset(
    {DataSubjectRequestType.EXPORT.value, DataSubjectRequestType.ERASE.value}
)
_APPROVABLE_REQUEST_TYPES = _FULFILMENT_PIPELINE_REQUEST_TYPES
_REPRESENTATIVE_APPROVAL_STATUSES = frozenset(
    {
        DataSubjectRequestRepresentativeStatus.NOT_REQUIRED.value,
        DataSubjectRequestRepresentativeStatus.VERIFIED.value,
    }
)
_REPRESENTATIVE_REVIEWABLE_REQUEST_STATUSES = frozenset(
    {
        DataSubjectRequestStatus.SUBMITTED.value,
        DataSubjectRequestStatus.UNDER_REVIEW.value,
    }
)
_ERASURE_EXECUTION_NOT_FOUND_REASON_CODES = frozenset(
    {
        "erasure_execution_request_not_found",
        "erasure_orchestration_request_not_found",
    }
)
_ERASURE_EXECUTION_FORBIDDEN_REASON_CODES = frozenset(
    {
        "erasure_execution_requires_platform_staff",
        "erasure_execution_requires_active_user",
        "erasure_execution_requires_active_staff",
        "erasure_execution_requires_privileged_staff",
        "erasure_execution_requires_non_subject_executor",
    }
)


class DataSubjectRequestService:
    DEFAULT_DUE_DAYS = 30
    EXTENSION_DAYS = 60
    MAX_DUE_DAYS = 90
    IDEMPOTENCY_KEY_TTL_HOURS = 24
    REQUESTER_NOTE_MAX_LENGTH = 2000
    REPRESENTATIVE_RELATIONSHIP_MAX_LENGTH = 64
    REPRESENTATIVE_AUTHORITY_NOTE_MAX_LENGTH = 2000

    _EMAIL_LIKE_PATTERN = re.compile(
        r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
        re.IGNORECASE,
    )
    _UNSAFE_IDEMPOTENCY_PATTERNS = (
        re.compile(r"^\s*bearer\s+[A-Z0-9._\-+/=]+", re.IGNORECASE),
        re.compile(r"^\s*basic\s+[A-Z0-9._\-+/=]+", re.IGNORECASE),
        re.compile(
            r"(api[_\-]?key|secret|password|passwd|token)\s*[:=]",
            re.IGNORECASE,
        ),
        re.compile(r"eyJ[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+"),
        re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}", re.IGNORECASE),
    )

    _ALLOWED_TRANSITIONS = {
        DataSubjectRequestStatus.SUBMITTED.value: {
            DataSubjectRequestStatus.UNDER_REVIEW.value,
            DataSubjectRequestStatus.APPROVED.value,
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
        self.session = session
        self.repository = DataSubjectRequestRepository(session)
        self.audit_events = AuditEventService(session)
        self.export_artifacts = ExportArtifactRepository(session)

    async def submit_request(
        self,
        *,
        requester_user_id: UUID,
        request_type: str,
        requester_note: str | None = None,
        subject_user_id: UUID | None = None,
        requester_role: str = DataSubjectRequestRequesterRole.SELF.value,
        representative_relationship: str | None = None,
        representative_authority_note: str | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
        audit_context: AuditContext,
    ) -> DataSubjectRequest:
        reference_now = now or datetime.now(UTC)
        normalised_request_type = self._normalise_request_type(request_type)
        normalised_idempotency_key = self._normalise_idempotency_key(idempotency_key)
        normalised_requester_role = self._normalise_requester_role(requester_role)
        normalised_representative_relationship = self._normalise_optional_text(
            representative_relationship
        )
        normalised_representative_authority_note = self._normalise_optional_text(
            representative_authority_note
        )

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
        representative_values = self._build_representative_intake_values(
            requester_user_id=requester_user_id,
            subject_user_id=subject_user_id,
            requester_role=normalised_requester_role,
            representative_relationship=normalised_representative_relationship,
            representative_authority_note=normalised_representative_authority_note,
        )
        await self._ensure_representative_subject_exists(
            requester_role=normalised_requester_role,
            subject_user_id=representative_values["subject_user_id"],
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
                subject_user_id=representative_values["subject_user_id"],
                requester_role=representative_values["requester_role"],
                representative_relationship=representative_values[
                    "representative_relationship"
                ],
                representative_authority_note=representative_values[
                    "representative_authority_note"
                ],
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
            **representative_values,
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
        if target_status is DataSubjectRequestStatus.FULFILLED:
            raise ConflictError(
                detail=("Use fulfil_request() to fulfil data-subject requests")
            )

        return await self._transition_status(
            request_id=request_id,
            target_status=target_status,
            reviewer_user_id=reviewer_user_id,
            audit_context=audit_context,
            reason_code=reason_code,
            now=now,
        )

    async def _transition_status(
        self,
        *,
        request_id: UUID,
        target_status: DataSubjectRequestStatus,
        reviewer_user_id: UUID | None,
        audit_context: AuditContext,
        reason_code: str | None = None,
        now: datetime | None = None,
        execution_verified: bool = False,
    ) -> DataSubjectRequest:
        reference_now = now or datetime.now(UTC)
        request = await self.get_request(request_id=request_id)
        current_status = request.status
        next_status = target_status.value

        if (
            target_status is DataSubjectRequestStatus.FULFILLED
            and not execution_verified
        ):
            raise ConflictError(
                detail=("Use fulfil_request() to fulfil data-subject requests")
            )

        allowed = self._ALLOWED_TRANSITIONS.get(current_status, set())
        if next_status not in allowed:
            raise ConflictError(
                detail=f"Invalid transition from '{current_status}' to '{next_status}'"
            )

        if target_status is DataSubjectRequestStatus.APPROVED:
            self._ensure_request_type_can_be_approved(request)
            self._ensure_representative_authority_allows_approval(request)

        updated = await self.repository.transition_status_if_current(
            request_id=request_id,
            expected_status=current_status,
            values=self._build_transition_values(
                next_status=next_status,
                reviewer_user_id=reviewer_user_id,
                reason_code=reason_code,
                reference_now=reference_now,
            ),
        )
        if updated is None:
            latest = await self.repository.get_by_id(
                request_id,
                populate_existing=True,
            )
            if latest is None:
                raise NotFoundError(detail="Data subject request not found")
            raise ConflictError(
                detail=(
                    "Data subject request status changed during transition; "
                    f"current status is '{latest.status}'"
                )
            )

        await self._record_status_event(
            request=updated,
            action=self._action_for_status(target_status),
            audit_context=audit_context,
        )
        return updated

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
            representative_status=kwargs.get("representative_status"),
        )
        return rows, total

    async def get_platform_request(self, *, request_id: UUID) -> DataSubjectRequest:
        return await self.get_request(request_id=request_id)

    async def execute_approved_erasure_request_by_platform_staff(
        self,
        *,
        request_id: UUID,
        executor_user_id: UUID,
        audit_context: AuditContext,
        now: datetime | None = None,
    ) -> DataSubjectRequest:
        try:
            await execute_approved_erasure_request_by_staff(
                self.session,
                request_id=request_id,
                executor_user_id=executor_user_id,
                now=now,
            )
        except (ErasureExecutionError, ErasureOrchestrationError) as exc:
            self._raise_erasure_execution_app_error(exc.reason_code)

        request = await self.get_platform_request(request_id=request_id)
        if self._is_ready_approved_erasure_request(request):
            return await self._transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.FULFILLED,
                reviewer_user_id=self._fulfilment_reviewer_user_id(
                    request,
                    executor_user_id,
                ),
                audit_context=audit_context,
                execution_verified=True,
            )

        return request

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

    async def verify_representative_authority(
        self,
        *,
        request_id: UUID,
        reviewer_user_id: UUID,
        reason_code: str | None,
        audit_context: AuditContext,
        now: datetime | None = None,
    ) -> DataSubjectRequest:
        reference_now = now or datetime.now(UTC)
        request = await self.get_platform_request(request_id=request_id)
        self._ensure_representative_authority_reviewable(request)

        request.representative_status = (
            DataSubjectRequestRepresentativeStatus.VERIFIED.value
        )
        request.representative_verified_at = reference_now
        request.representative_verified_by_user_id = reviewer_user_id
        request.representative_rejection_reason_code = None
        updated = await self.repository.save(request)
        await self._record_representative_authority_event(
            request=updated,
            action=AuditAction.DATA_SUBJECT_REQUEST_REPRESENTATIVE_VERIFIED,
            audit_context=audit_context,
            reason_code=reason_code,
        )
        return updated

    async def reject_representative_authority(
        self,
        *,
        request_id: UUID,
        reviewer_user_id: UUID,
        reason_code: str,
        audit_context: AuditContext,
    ) -> DataSubjectRequest:
        del reviewer_user_id
        request = await self.get_platform_request(request_id=request_id)
        self._ensure_representative_authority_reviewable(request)

        request.representative_status = (
            DataSubjectRequestRepresentativeStatus.REJECTED.value
        )
        request.representative_verified_at = None
        request.representative_verified_by_user_id = None
        request.representative_rejection_reason_code = reason_code
        updated = await self.repository.save(request)
        await self._record_representative_authority_event(
            request=updated,
            action=AuditAction.DATA_SUBJECT_REQUEST_REPRESENTATIVE_REJECTED,
            audit_context=audit_context,
            reason_code=reason_code,
        )
        return updated

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
        await self._ensure_execution_ready_for_fulfilment(request)
        fulfilment_reviewer_user_id = self._fulfilment_reviewer_user_id(
            request,
            reviewer_user_id,
        )
        return await self._transition_status(
            request_id=request_id,
            target_status=DataSubjectRequestStatus.FULFILLED,
            reviewer_user_id=fulfilment_reviewer_user_id,
            audit_context=audit_context,
            execution_verified=True,
        )

    async def _ensure_execution_ready_for_fulfilment(
        self, request: DataSubjectRequest
    ) -> None:
        if request.request_type not in _FULFILMENT_PIPELINE_REQUEST_TYPES:
            raise ConflictError(
                detail=(
                    "Execution pipeline is not implemented for "
                    f"'{request.request_type}' data-subject requests"
                )
            )

        if request.request_type == DataSubjectRequestType.ERASE.value:
            self._ensure_erasure_ready_for_fulfilment(request)
            return

        await self._ensure_export_ready_for_fulfilment(request)

    @staticmethod
    def _ensure_request_type_can_be_approved(request: DataSubjectRequest) -> None:
        if request.request_type in _APPROVABLE_REQUEST_TYPES:
            return
        raise ConflictError(
            detail=(
                "Data-subject request type has no execution policy and cannot "
                "be approved"
            )
        )

    @staticmethod
    def _ensure_representative_authority_allows_approval(
        request: DataSubjectRequest,
    ) -> None:
        if request.representative_status in _REPRESENTATIVE_APPROVAL_STATUSES:
            return
        raise ConflictError(
            detail=(
                "Authorised representative authority must be verified before approval"
            )
        )

    async def _ensure_export_ready_for_fulfilment(
        self, request: DataSubjectRequest
    ) -> None:
        artifacts = await self.export_artifacts.get_by_dsr_id(request.id)
        now = datetime.now(UTC)
        for artifact in artifacts:
            if self._is_ready_export_artifact_usable(artifact, now=now):
                return
        raise ConflictError(
            detail=(
                "Export data-subject requests require a ready, non-expired "
                "export artifact before fulfilment"
            )
        )

    @staticmethod
    def _ensure_erasure_ready_for_fulfilment(request: DataSubjectRequest) -> None:
        if request.execution_status == DataSubjectRequestExecutionStatus.READY.value:
            return

        raise ConflictError(
            detail=(
                "Erase data-subject requests require successful erasure execution "
                "before fulfilment"
            )
        )

    @staticmethod
    def _fulfilment_reviewer_user_id(
        request: DataSubjectRequest,
        reviewer_user_id: UUID,
    ) -> UUID | None:
        if request.request_type == DataSubjectRequestType.ERASE.value:
            return None

        return reviewer_user_id

    @staticmethod
    def _is_ready_approved_erasure_request(request: DataSubjectRequest) -> bool:
        return (
            request.request_type == DataSubjectRequestType.ERASE.value
            and request.status == DataSubjectRequestStatus.APPROVED.value
            and request.execution_status
            == DataSubjectRequestExecutionStatus.READY.value
        )

    @staticmethod
    def _is_ready_export_artifact_usable(
        artifact: ExportArtifact, *, now: datetime
    ) -> bool:
        if artifact.status != ExportArtifactStatus.READY.value:
            return False

        expires_at = artifact.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        else:
            expires_at = expires_at.astimezone(UTC)
        return expires_at > now

    @staticmethod
    def _build_transition_values(
        *,
        next_status: str,
        reviewer_user_id: UUID | None,
        reason_code: str | None,
        reference_now: datetime,
    ) -> dict[str, object | None]:
        values: dict[str, object | None] = {
            "status": next_status,
            "reviewer_user_id": reviewer_user_id,
        }

        if next_status == DataSubjectRequestStatus.UNDER_REVIEW.value:
            values["reviewed_at"] = reference_now
        if next_status in {
            DataSubjectRequestStatus.APPROVED.value,
            DataSubjectRequestStatus.REJECTED.value,
        }:
            values["decided_at"] = reference_now
        if next_status == DataSubjectRequestStatus.FULFILLED.value:
            values["fulfilled_at"] = reference_now
        if next_status == DataSubjectRequestStatus.CANCELLED.value:
            values["cancelled_at"] = reference_now
        if next_status == DataSubjectRequestStatus.REJECTED.value:
            values["rejection_reason_code"] = reason_code
        if next_status == DataSubjectRequestStatus.APPROVED.value:
            values["decision_reason_code"] = reason_code

        return values

    @staticmethod
    def _raise_erasure_execution_app_error(reason_code: str) -> None:
        if reason_code in _ERASURE_EXECUTION_NOT_FOUND_REASON_CODES:
            raise NotFoundError(detail="Data subject request not found") from None
        if reason_code in _ERASURE_EXECUTION_FORBIDDEN_REASON_CODES:
            raise ForbiddenError(detail="Platform access denied") from None
        raise ConflictError(
            detail="Erasure execution is not eligible in the current state",
            extra={"reason_code": reason_code},
        ) from None

    @staticmethod
    def _normalise_idempotency_key(key: str | None) -> str | None:
        if key is None:
            return None
        return key.strip()

    @staticmethod
    def _hash_idempotency_key(key: str) -> str:
        return sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalise_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalised = value.strip()
        return normalised or None

    @staticmethod
    def _normalise_requester_role(role: str) -> str:
        try:
            return DataSubjectRequestRequesterRole(role).value
        except ValueError as exc:
            raise BadRequestError(
                detail=(
                    "Invalid requester_role. Supported values: "
                    "self, authorised_representative"
                )
            ) from exc

    def _build_representative_intake_values(
        self,
        *,
        requester_user_id: UUID,
        subject_user_id: UUID | None,
        requester_role: str,
        representative_relationship: str | None,
        representative_authority_note: str | None,
    ) -> dict[str, object | None]:
        if requester_role == DataSubjectRequestRequesterRole.SELF.value:
            if subject_user_id is not None and subject_user_id != requester_user_id:
                raise BadRequestError(
                    detail=(
                        "subject_user_id is only allowed for representative requests"
                    )
                )
            if representative_relationship is not None:
                raise BadRequestError(
                    detail=(
                        "representative_relationship is only allowed for "
                        "representative requests"
                    )
                )
            if representative_authority_note is not None:
                raise BadRequestError(
                    detail=(
                        "representative_authority_note is only allowed for "
                        "representative requests"
                    )
                )
            return {
                "subject_user_id": requester_user_id,
                "requester_role": DataSubjectRequestRequesterRole.SELF.value,
                "representative_status": (
                    DataSubjectRequestRepresentativeStatus.NOT_REQUIRED.value
                ),
                "representative_relationship": None,
                "representative_authority_note": None,
                "representative_verified_at": None,
                "representative_verified_by_user_id": None,
                "representative_rejection_reason_code": None,
            }

        if subject_user_id is None:
            raise BadRequestError(
                detail="subject_user_id is required for representative requests"
            )
        if subject_user_id == requester_user_id:
            raise BadRequestError(
                detail=("Representative requests must target a different subject user")
            )
        if representative_relationship is None:
            raise BadRequestError(
                detail=(
                    "representative_relationship is required for "
                    "representative requests"
                )
            )
        if representative_authority_note is None:
            raise BadRequestError(
                detail=(
                    "representative_authority_note is required for "
                    "representative requests"
                )
            )
        if (
            len(representative_relationship)
            > self.REPRESENTATIVE_RELATIONSHIP_MAX_LENGTH
        ):
            raise BadRequestError(
                detail=(
                    "Representative relationship exceeds maximum length of "
                    f"{self.REPRESENTATIVE_RELATIONSHIP_MAX_LENGTH} characters"
                )
            )
        if (
            len(representative_authority_note)
            > self.REPRESENTATIVE_AUTHORITY_NOTE_MAX_LENGTH
        ):
            raise BadRequestError(
                detail=(
                    "Representative authority note exceeds maximum length of "
                    f"{self.REPRESENTATIVE_AUTHORITY_NOTE_MAX_LENGTH} characters"
                )
            )

        return {
            "subject_user_id": subject_user_id,
            "requester_role": (
                DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
            ),
            "representative_status": (
                DataSubjectRequestRepresentativeStatus.PENDING_VERIFICATION.value
            ),
            "representative_relationship": representative_relationship,
            "representative_authority_note": representative_authority_note,
            "representative_verified_at": None,
            "representative_verified_by_user_id": None,
            "representative_rejection_reason_code": None,
        }

    async def _ensure_representative_subject_exists(
        self,
        *,
        requester_role: str,
        subject_user_id: object | None,
    ) -> None:
        if requester_role != (
            DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
        ):
            return
        if not isinstance(subject_user_id, UUID):
            raise BadRequestError(
                detail="subject_user_id is required for representative requests"
            )
        stmt = select(User.id).where(User.id == subject_user_id)
        existing_subject_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing_subject_id is None:
            raise BadRequestError(detail="Representative subject user was not found")

    @staticmethod
    def _ensure_representative_authority_reviewable(
        request: DataSubjectRequest,
    ) -> None:
        if request.requester_role != (
            DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value
        ):
            raise ConflictError(
                detail=(
                    "Representative authority review is only valid for "
                    "authorised-representative requests"
                )
            )
        if request.status not in _REPRESENTATIVE_REVIEWABLE_REQUEST_STATUSES:
            raise ConflictError(
                detail=(
                    "Representative authority cannot be changed after the "
                    "request has been decided, fulfilled or cancelled"
                )
            )

    async def _record_representative_authority_event(
        self,
        *,
        request: DataSubjectRequest,
        action: AuditAction,
        audit_context: AuditContext,
        reason_code: str | None,
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
                "representative_status": request.representative_status,
                "reason_code": reason_code,
            },
        )

    @staticmethod
    def _build_fingerprint(
        *,
        request_type: str,
        requester_note: str | None,
        subject_user_id: object,
        requester_role: object,
        representative_relationship: object,
        representative_authority_note: object,
    ) -> str:
        fingerprint_source = "|".join(
            (
                f"request_type={request_type}",
                f"requester_note={requester_note or ''}",
                f"subject_user_id={subject_user_id}",
                f"requester_role={requester_role}",
                (f"representative_relationship={representative_relationship or ''}"),
                (
                    "representative_authority_note="
                    f"{representative_authority_note or ''}"
                ),
            )
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
