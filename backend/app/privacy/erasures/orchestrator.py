from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.invites.models.invite import Invite
from app.privacy.erasures.audit import (
    AuditErasureError,
    minimise_audit_events_for_approved_erase_request,
)
from app.privacy.erasures.invite import (
    InviteErasureError,
    anonymise_invites_for_approved_erase_request,
)
from app.privacy.erasures.outbox import (
    OutboxErasureError,
    scrub_outbox_for_approved_erase_request,
)
from app.privacy.erasures.remaining_inventory import (
    RemainingInventoryErasureError,
    apply_membership_erasure_policy,
    apply_organisation_erasure_policy,
    minimise_dsr_workflow_for_approved_erase_request,
    minimise_export_artifacts_for_approved_erase_request,
    minimise_platform_staff_for_approved_erase_request,
    minimise_privacy_governance_for_approved_erase_request,
)
from app.privacy.erasures.user_profile import (
    UserProfileErasureError,
    anonymise_user_profile_for_approved_erase_request,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.provider_keys import (
    erasure_orchestration_provider_order as _provider_key_order,
)
from app.users.models.user import User

_GENERIC_FAILURE_REASON_CODE = "erasure_orchestration_failed"
_ALREADY_PROCESSING_REASON_CODE = "erasure_orchestration_already_processing"


def erasure_orchestration_provider_order() -> tuple[str, ...]:
    """Return the central erasure provider execution order.

    Kept as a compatibility export for callers that historically imported
    the provider order from this module while the source of truth lives in
    ``app.privacy.provider_keys``.
    """

    return _provider_key_order()


class ErasureOrchestrationStatus(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    FAILED = "failed"


class ErasureOrchestrationError(ValueError):
    """Raised when the core erasure orchestration is not eligible to run."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ErasureProviderRunResult:
    provider_key: str
    table_name: str
    decision: str
    affected_rows: int
    changed_fields: tuple[str, ...]

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0

    @property
    def requires_manual_review(self) -> bool:
        return self.decision == "manual_review_policy"

    @property
    def retained_by_policy(self) -> bool:
        return self.decision == "retained_by_policy"


@dataclass(frozen=True, slots=True)
class ErasureOrchestrationResult:
    request_id: UUID
    subject_user_id: UUID | None
    status: ErasureOrchestrationStatus
    provider_results: tuple[ErasureProviderRunResult, ...]
    completed_at: datetime
    failure_reason_code: str | None = None

    @property
    def provider_keys(self) -> tuple[str, ...]:
        return tuple(result.provider_key for result in self.provider_results)

    @property
    def affected_rows(self) -> int:
        return sum(result.affected_rows for result in self.provider_results)

    @property
    def did_mutate(self) -> bool:
        return any(result.did_mutate for result in self.provider_results)


@dataclass(frozen=True, slots=True)
class _ErasureSnapshot:
    subject_user_id: UUID
    subject_email: str | None
    invite_ids: tuple[UUID, ...]


async def execute_core_erasure_for_approved_request(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    now: datetime | None = None,
) -> ErasureOrchestrationResult:
    """Run the currently implemented core erasure providers in safe order.

    This orchestration is intentionally internal. It does not commit, does not
    expose an API endpoint, and does not fulfil the DSR. Validation errors are
    raised before execution starts. Provider failures are returned as failed
    results so normal outer transaction managers can commit the failed state.
    """

    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    locked_request = await _lock_and_validate_request(session, request)
    if _execution_status(locked_request) is DataSubjectRequestExecutionStatus.READY:
        return ErasureOrchestrationResult(
            request_id=locked_request.id,
            subject_user_id=locked_request.subject_user_id,
            status=ErasureOrchestrationStatus.ALREADY_COMPLETED,
            provider_results=(),
            completed_at=reference_now,
        )

    subject_user_id = _subject_user_id(locked_request)
    _mark_processing(locked_request, now=reference_now)
    await session.flush()

    try:
        async with session.begin_nested():
            snapshot = await _build_snapshot(session, locked_request)
            provider_results = await _run_core_providers(
                session,
                locked_request,
                snapshot=snapshot,
                subject_user_id=subject_user_id,
                now=reference_now,
            )
    except _PROVIDER_ERRORS as exc:
        reason_code = exc.reason_code
        await _mark_failed(
            session,
            locked_request,
            reason_code=reason_code,
            now=reference_now,
        )
        return _failed_result(
            request_id=locked_request.id,
            subject_user_id=subject_user_id,
            reason_code=reason_code,
            completed_at=reference_now,
        )
    except Exception:
        await _mark_failed(
            session,
            locked_request,
            reason_code=_GENERIC_FAILURE_REASON_CODE,
            now=reference_now,
        )
        return _failed_result(
            request_id=locked_request.id,
            subject_user_id=subject_user_id,
            reason_code=_GENERIC_FAILURE_REASON_CODE,
            completed_at=reference_now,
        )

    _mark_ready(locked_request, now=reference_now)
    await session.flush()
    return ErasureOrchestrationResult(
        request_id=locked_request.id,
        subject_user_id=subject_user_id,
        status=ErasureOrchestrationStatus.COMPLETED,
        provider_results=provider_results,
        completed_at=reference_now,
    )


async def _lock_and_validate_request(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> DataSubjectRequest:
    stmt = (
        select(DataSubjectRequest)
        .where(DataSubjectRequest.id == request.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked_request = (await session.execute(stmt)).scalar_one_or_none()
    if locked_request is None:
        raise ErasureOrchestrationError("erasure_orchestration_request_not_found")
    if locked_request.request_type != DataSubjectRequestType.ERASE.value:
        raise ErasureOrchestrationError("erasure_orchestration_requires_erase_request")

    execution_status = _execution_status(locked_request)
    if execution_status is DataSubjectRequestExecutionStatus.READY:
        return locked_request

    if locked_request.status != DataSubjectRequestStatus.APPROVED.value:
        raise ErasureOrchestrationError(
            "erasure_orchestration_requires_approved_request"
        )
    if execution_status is DataSubjectRequestExecutionStatus.PROCESSING:
        raise ErasureOrchestrationError(_ALREADY_PROCESSING_REASON_CODE)
    if locked_request.subject_user_id is None:
        raise ErasureOrchestrationError("erasure_orchestration_requires_subject_user")
    return locked_request


async def _build_snapshot(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> _ErasureSnapshot:
    subject = await _lock_subject(session, subject_user_id=_subject_user_id(request))
    subject_email = _normalise_optional_email(subject.email)
    invite_ids = await _subject_invite_ids(
        session,
        subject_user_id=subject.id,
        subject_email=subject_email,
    )
    return _ErasureSnapshot(
        subject_user_id=subject.id,
        subject_email=subject_email,
        invite_ids=invite_ids,
    )


async def _lock_subject(session: AsyncSession, *, subject_user_id: UUID) -> User:
    stmt = (
        select(User)
        .where(User.id == subject_user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    subject = (await session.execute(stmt)).scalar_one_or_none()
    if subject is None:
        raise ErasureOrchestrationError("erasure_orchestration_subject_not_found")
    return subject


async def _subject_invite_ids(
    session: AsyncSession,
    *,
    subject_user_id: UUID,
    subject_email: str | None,
) -> tuple[UUID, ...]:
    conditions: list[object] = [Invite.revoked_by_user_id == subject_user_id]
    if subject_email is not None:
        conditions.append(func.lower(func.trim(Invite.email)) == subject_email)

    stmt = select(Invite.id).where(or_(*conditions)).order_by(Invite.id.asc())
    return tuple((await session.execute(stmt)).scalars().all())


async def _run_core_providers(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    snapshot: _ErasureSnapshot,
    subject_user_id: UUID,
    now: datetime,
) -> tuple[ErasureProviderRunResult, ...]:
    audit_result = await minimise_audit_events_for_approved_erase_request(
        session,
        request,
        now=now,
    )
    outbox_result = await scrub_outbox_for_approved_erase_request(
        session,
        request,
        subject_email=snapshot.subject_email,
        invite_ids=snapshot.invite_ids,
        now=now,
    )
    invite_result = await anonymise_invites_for_approved_erase_request(
        session,
        request,
        subject_email=snapshot.subject_email,
        now=now,
    )
    membership_result = await apply_membership_erasure_policy(
        session,
        request,
        subject_user_id=subject_user_id,
        now=now,
    )
    organisation_result = await apply_organisation_erasure_policy(
        session,
        request,
        subject_user_id=subject_user_id,
        now=now,
    )
    platform_staff_result = await minimise_platform_staff_for_approved_erase_request(
        session,
        request,
        subject_user_id=subject_user_id,
        now=now,
    )
    export_artifact_result = await minimise_export_artifacts_for_approved_erase_request(
        session,
        request,
        subject_user_id=subject_user_id,
        now=now,
    )
    privacy_governance_results = (
        await minimise_privacy_governance_for_approved_erase_request(
            session,
            request,
            subject_user_id=subject_user_id,
            now=now,
        )
    )
    user_result = await anonymise_user_profile_for_approved_erase_request(
        session,
        request,
        now=now,
    )
    dsr_result = await minimise_dsr_workflow_for_approved_erase_request(
        session,
        request,
        subject_user_id=subject_user_id,
        now=now,
    )
    provider_results = (
        audit_result,
        outbox_result,
        invite_result,
        membership_result,
        organisation_result,
        platform_staff_result,
        export_artifact_result,
        *privacy_governance_results,
        user_result,
        dsr_result,
    )
    return tuple(_provider_result_from_provider(result) for result in provider_results)


_PROVIDER_ERRORS = (
    AuditErasureError,
    InviteErasureError,
    OutboxErasureError,
    UserProfileErasureError,
    RemainingInventoryErasureError,
    ErasureOrchestrationError,
)


def _provider_result_from_provider(result: object) -> ErasureProviderRunResult:
    return _provider_result(
        provider_key=result.provider_key,
        table_name=result.table_name,
        decision=result.status,
        affected_rows=result.affected_rows,
        changed_fields=result.changed_fields,
    )


def _provider_result(
    *,
    provider_key: str,
    table_name: str,
    decision: object,
    affected_rows: int,
    changed_fields: tuple[str, ...],
) -> ErasureProviderRunResult:
    return ErasureProviderRunResult(
        provider_key=provider_key,
        table_name=table_name,
        decision=_provider_decision_value(decision),
        affected_rows=affected_rows,
        changed_fields=changed_fields,
    )


def _provider_decision_value(decision: object) -> str:
    if isinstance(decision, StrEnum):
        return decision.value
    if isinstance(decision, str):
        return decision
    return str(decision)


def _failed_result(
    *,
    request_id: UUID,
    subject_user_id: UUID,
    reason_code: str,
    completed_at: datetime,
) -> ErasureOrchestrationResult:
    return ErasureOrchestrationResult(
        request_id=request_id,
        subject_user_id=subject_user_id,
        status=ErasureOrchestrationStatus.FAILED,
        provider_results=(),
        completed_at=completed_at,
        failure_reason_code=reason_code[:64],
    )


def _mark_processing(request: DataSubjectRequest, *, now: datetime) -> None:
    request.execution_status = DataSubjectRequestExecutionStatus.PROCESSING.value
    request.execution_started_at = now
    request.execution_completed_at = None
    request.execution_failed_at = None
    request.execution_failure_reason_code = None
    request.execution_failure_detail = None


def _mark_ready(request: DataSubjectRequest, *, now: datetime) -> None:
    request.execution_status = DataSubjectRequestExecutionStatus.READY.value
    request.execution_completed_at = now
    request.execution_failed_at = None
    request.execution_failure_reason_code = None
    request.execution_failure_detail = None


async def _mark_failed(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    reason_code: str,
    now: datetime,
) -> None:
    request.execution_status = DataSubjectRequestExecutionStatus.FAILED.value
    request.execution_failed_at = now
    request.execution_failure_reason_code = reason_code[:64]
    request.execution_failure_detail = None
    await session.flush()


def _execution_status(
    request: DataSubjectRequest,
) -> DataSubjectRequestExecutionStatus:
    return DataSubjectRequestExecutionStatus(request.execution_status)


def _subject_user_id(request: DataSubjectRequest) -> UUID:
    if request.subject_user_id is None:
        raise ErasureOrchestrationError("erasure_orchestration_requires_subject_user")
    return request.subject_user_id


def _normalise_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip().lower()
    return normalised or None


def _normalise_reference_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
