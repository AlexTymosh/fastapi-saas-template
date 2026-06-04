from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.invites.models.invite import Invite
from app.privacy.erasures.invite import (
    InviteErasureError,
    anonymise_invites_for_approved_erase_request,
)
from app.privacy.erasures.outbox import (
    OutboxErasureError,
    scrub_outbox_for_approved_erase_request,
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
from app.users.models.user import User

_OUTBOX_PROVIDER_KEY = "outbox.purge_or_scrub_payload"
_INVITES_PROVIDER_KEY = "invites.anonymise_or_purge_subject_references"
_USERS_PROVIDER_KEY = "users.anonymise_profile"
_PROVIDER_ORDER = (
    _OUTBOX_PROVIDER_KEY,
    _INVITES_PROVIDER_KEY,
    _USERS_PROVIDER_KEY,
)
_GENERIC_FAILURE_REASON_CODE = "erasure_orchestration_failed"
_ALREADY_PROCESSING_REASON_CODE = "erasure_orchestration_already_processing"


class ErasureOrchestrationStatus(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"


class ErasureOrchestrationError(ValueError):
    """Raised when the core erasure provider orchestration cannot complete."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ErasureProviderRunResult:
    provider_key: str
    table_name: str
    affected_rows: int
    changed_fields: tuple[str, ...]

    @property
    def did_mutate(self) -> bool:
        return self.affected_rows > 0


@dataclass(frozen=True, slots=True)
class ErasureOrchestrationResult:
    request_id: UUID
    subject_user_id: UUID
    status: ErasureOrchestrationStatus
    provider_results: tuple[ErasureProviderRunResult, ...]
    completed_at: datetime

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
    expose an API endpoint, and does not fulfil the DSR. It records execution
    status on the request so later worker/API slices can reuse the same contract.
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

    _mark_processing(locked_request, now=reference_now)
    await session.flush()

    try:
        async with session.begin_nested():
            snapshot = await _build_snapshot(session, locked_request)
            provider_results = await _run_core_providers(
                session,
                locked_request,
                snapshot=snapshot,
                now=reference_now,
            )
    except _PROVIDER_ERRORS as exc:
        await _mark_failed(session, locked_request, reason_code=exc.reason_code)
        raise ErasureOrchestrationError(exc.reason_code) from exc
    except Exception as exc:
        await _mark_failed(
            session,
            locked_request,
            reason_code=_GENERIC_FAILURE_REASON_CODE,
        )
        raise ErasureOrchestrationError(_GENERIC_FAILURE_REASON_CODE) from exc

    _mark_ready(locked_request, now=reference_now)
    await session.flush()
    return ErasureOrchestrationResult(
        request_id=locked_request.id,
        subject_user_id=locked_request.subject_user_id,
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
    if locked_request.status != DataSubjectRequestStatus.APPROVED.value:
        raise ErasureOrchestrationError(
            "erasure_orchestration_requires_approved_request"
        )
    if locked_request.subject_user_id is None:
        raise ErasureOrchestrationError("erasure_orchestration_requires_subject_user")
    if (
        _execution_status(locked_request)
        is DataSubjectRequestExecutionStatus.PROCESSING
    ):
        raise ErasureOrchestrationError(_ALREADY_PROCESSING_REASON_CODE)
    return locked_request


async def _build_snapshot(
    session: AsyncSession,
    request: DataSubjectRequest,
) -> _ErasureSnapshot:
    assert request.subject_user_id is not None
    subject = await session.get(User, request.subject_user_id)
    if subject is None:
        raise ErasureOrchestrationError("erasure_orchestration_subject_not_found")

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
    now: datetime,
) -> tuple[ErasureProviderRunResult, ...]:
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
    user_result = await anonymise_user_profile_for_approved_erase_request(
        session,
        request,
        now=now,
    )
    return (
        _provider_result(
            provider_key=outbox_result.provider_key,
            table_name=outbox_result.table_name,
            affected_rows=outbox_result.affected_rows,
            changed_fields=outbox_result.changed_fields,
        ),
        _provider_result(
            provider_key=invite_result.provider_key,
            table_name=invite_result.table_name,
            affected_rows=invite_result.affected_rows,
            changed_fields=invite_result.changed_fields,
        ),
        _provider_result(
            provider_key=user_result.provider_key,
            table_name=user_result.table_name,
            affected_rows=user_result.affected_rows,
            changed_fields=user_result.changed_fields,
        ),
    )


_PROVIDER_ERRORS = (
    InviteErasureError,
    OutboxErasureError,
    UserProfileErasureError,
    ErasureOrchestrationError,
)


def _provider_result(
    *,
    provider_key: str,
    table_name: str,
    affected_rows: int,
    changed_fields: tuple[str, ...],
) -> ErasureProviderRunResult:
    return ErasureProviderRunResult(
        provider_key=provider_key,
        table_name=table_name,
        affected_rows=affected_rows,
        changed_fields=changed_fields,
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
) -> None:
    request.execution_status = DataSubjectRequestExecutionStatus.FAILED.value
    request.execution_failed_at = datetime.now(UTC)
    request.execution_failure_reason_code = reason_code[:64]
    request.execution_failure_detail = None
    await session.flush()


def _execution_status(
    request: DataSubjectRequest,
) -> DataSubjectRequestExecutionStatus:
    return DataSubjectRequestExecutionStatus(request.execution_status)


def _normalise_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip().lower()
    return normalised or None


def _normalise_reference_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
