from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.privacy.erasures.orchestrator import (
    ErasureOrchestrationResult,
    ErasureOrchestrationStatus,
    execute_core_erasure_for_approved_request,
)
from app.privacy.models.data_subject_request import DataSubjectRequest
from app.users.models.user import User, UserStatus

_ALLOWED_EXECUTOR_ROLES = frozenset(
    {
        PlatformStaffRole.PLATFORM_ADMIN.value,
        PlatformStaffRole.COMPLIANCE_OFFICER.value,
    }
)
_EXECUTION_AUDIT_REASON = "approved_erasure_execution"


class ErasureExecutionError(ValueError):
    """Raised when a reviewer cannot execute an approved erasure request."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ErasureExecutionResult:
    request_id: UUID
    subject_user_id: UUID | None
    executor_user_id: UUID
    executor_role: str
    orchestration_status: ErasureOrchestrationStatus
    provider_keys: tuple[str, ...]
    affected_rows: int
    completed_at: datetime
    audit_event_id: UUID
    failure_reason_code: str | None = None

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0


async def execute_approved_erasure_request_by_staff(
    session: AsyncSession,
    *,
    request_id: UUID,
    executor_user_id: UUID,
    now: datetime | None = None,
) -> ErasureExecutionResult:
    """Authorise and execute an approved erase DSR through the orchestrator.

    This is an internal command-layer boundary. It does not commit and does not
    expose an API endpoint. Public/API/worker layers should call this function
    inside their normal transaction boundary.
    """

    reference_now = _normalise_reference_time(now or datetime.now(UTC))
    executor = await _lock_authorised_executor(
        session,
        executor_user_id=executor_user_id,
    )
    request = await _lock_request(session, request_id=request_id)
    _reject_self_erasure(executor=executor, request=request)
    orchestration = await execute_core_erasure_for_approved_request(
        session,
        request,
        now=reference_now,
    )
    audit_event = _audit_execution(
        orchestration=orchestration,
        executor=executor,
        completed_at=reference_now,
    )
    session.add(audit_event)
    await session.flush()
    return _execution_result(
        orchestration=orchestration,
        executor=executor,
        completed_at=reference_now,
        audit_event_id=audit_event.id,
    )


async def _lock_authorised_executor(
    session: AsyncSession,
    *,
    executor_user_id: UUID,
) -> PlatformStaff:
    stmt = (
        select(PlatformStaff, User.status)
        .join(User, User.id == PlatformStaff.user_id)
        .where(PlatformStaff.user_id == executor_user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise ErasureExecutionError("erasure_execution_requires_platform_staff")

    executor, user_status = row
    if not _is_active_user_status(user_status):
        raise ErasureExecutionError("erasure_execution_requires_active_user")
    if executor.status != PlatformStaffStatus.ACTIVE.value:
        raise ErasureExecutionError("erasure_execution_requires_active_staff")
    if executor.role not in _ALLOWED_EXECUTOR_ROLES:
        raise ErasureExecutionError("erasure_execution_requires_privileged_staff")
    return executor


async def _lock_request(
    session: AsyncSession,
    *,
    request_id: UUID,
) -> DataSubjectRequest:
    stmt = (
        select(DataSubjectRequest)
        .where(DataSubjectRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    request = (await session.execute(stmt)).scalar_one_or_none()
    if request is None:
        raise ErasureExecutionError("erasure_execution_request_not_found")
    return request


def _reject_self_erasure(
    *,
    executor: PlatformStaff,
    request: DataSubjectRequest,
) -> None:
    if request.subject_user_id is None:
        return
    if executor.user_id == request.subject_user_id:
        raise ErasureExecutionError("erasure_execution_requires_non_subject_executor")


def _audit_execution(
    *,
    orchestration: ErasureOrchestrationResult,
    executor: PlatformStaff,
    completed_at: datetime,
) -> AuditEvent:
    return AuditEvent(
        actor_user_id=executor.user_id,
        category=AuditCategory.COMPLIANCE.value,
        action=AuditAction.DATA_SUBJECT_REQUEST_ERASURE_EXECUTED.value,
        target_type=AuditTargetType.DATA_SUBJECT_REQUEST.value,
        target_id=orchestration.request_id,
        reason=_EXECUTION_AUDIT_REASON,
        metadata_json=_audit_metadata(orchestration),
        created_at=completed_at,
    )


def _audit_metadata(
    orchestration: ErasureOrchestrationResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "orchestration_status": orchestration.status.value,
        "provider_keys": list(orchestration.provider_keys),
        "affected_rows": orchestration.affected_rows,
        "did_mutate": orchestration.did_mutate,
    }
    if orchestration.failure_reason_code is not None:
        metadata["failure_reason_code"] = orchestration.failure_reason_code
    return metadata


def _execution_result(
    *,
    orchestration: ErasureOrchestrationResult,
    executor: PlatformStaff,
    completed_at: datetime,
    audit_event_id: UUID,
) -> ErasureExecutionResult:
    return ErasureExecutionResult(
        request_id=orchestration.request_id,
        subject_user_id=orchestration.subject_user_id,
        executor_user_id=executor.user_id,
        executor_role=executor.role,
        orchestration_status=orchestration.status,
        provider_keys=orchestration.provider_keys,
        affected_rows=orchestration.affected_rows,
        completed_at=completed_at,
        audit_event_id=audit_event_id,
        failure_reason_code=orchestration.failure_reason_code,
    )


def _is_active_user_status(value: object) -> bool:
    return value == UserStatus.ACTIVE or value == UserStatus.ACTIVE.value


def _normalise_reference_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
