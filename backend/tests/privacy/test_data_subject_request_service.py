from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditEvent
from app.core.errors import BadRequestError, ConflictError
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.repositories.data_subject_requests import DataSubjectRequestRepository
from app.privacy.services.data_subject_requests import DataSubjectRequestService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


class _StatementCaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return None


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


async def _create_ready_export_artifact(
    session,
    *,
    request: DataSubjectRequest,
    user: User,
    expires_at: datetime | None = None,
) -> ExportArtifact:
    artifact = ExportArtifact(
        data_subject_request_id=request.id,
        subject_user_id=request.subject_user_id,
        requester_user_id=request.requester_user_id,
        status=ExportArtifactStatus.READY.value,
        format=ExportArtifactFormat.JSON_ZIP.value,
        storage_backend=ExportArtifactStorageBackend.LOCAL.value,
        schema_version="1.0",
        requested_by_user_id=user.id,
        queued_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=1),
    )
    session.add(artifact)
    await session.flush()
    await session.refresh(artifact)
    return artifact


def test_idempotency_requester_lock_uses_no_key_update() -> None:
    async def _run() -> None:
        session = _StatementCaptureSession()
        repository = DataSubjectRequestRepository(session)  # type: ignore[arg-type]

        await repository.lock_requester_for_idempotency(requester_user_id=uuid4())

        assert session.statement is not None
        compiled = str(session.statement.compile(dialect=postgresql.dialect()))
        assert "FOR NO KEY UPDATE" in compiled

    run_async(_run())


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


def test_submit_request_rejects_invalid_request_type(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="invalid-type@example.com")
            service = DataSubjectRequestService(session)
            with pytest.raises(BadRequestError):
                await service.submit_request(
                    requester_user_id=user.id,
                    request_type="unknown",
                    audit_context=AuditContext(actor_user_id=user.id),
                )

    run_async(_run())


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "john.doe@example.com",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig",
        "Basic dXNlcjpwYXNzd29yZA==",
        "token=secret_value",
    ],
)
def test_submit_request_rejects_unsafe_idempotency_key(
    migrated_session_factory, unsafe_key: str
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="unsafe-idempotency@example.com")
            service = DataSubjectRequestService(session)
            with pytest.raises(BadRequestError):
                await service.submit_request(
                    requester_user_id=user.id,
                    request_type="export",
                    idempotency_key=unsafe_key,
                    audit_context=AuditContext(actor_user_id=user.id),
                )

    run_async(_run())


def test_submit_request_validates_idempotency_key_before_hashing(
    migrated_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="idempotency-order@example.com")
            service = DataSubjectRequestService(session)

            def _fail_if_called(key: str) -> str:
                raise AssertionError("idempotency key was hashed before validation")

            monkeypatch.setattr(service, "_hash_idempotency_key", _fail_if_called)

            with pytest.raises(BadRequestError):
                await service.submit_request(
                    requester_user_id=user.id,
                    request_type="export",
                    idempotency_key="x" * 513,
                    audit_context=AuditContext(actor_user_id=user.id),
                )

    run_async(_run())


def test_idempotency_locks_requester_before_lookup(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="idempotency-lock@example.com")
            service = DataSubjectRequestService(session)
            calls: list[str] = []

            original_lock = service.repository.lock_requester_for_idempotency
            original_lookup = service.repository.get_non_expired_by_idempotency_key_hash

            async def _lock_requester_for_idempotency(*, requester_user_id):
                calls.append("lock")
                await original_lock(requester_user_id=requester_user_id)

            async def _get_non_expired_by_idempotency_key_hash(**kwargs):
                calls.append("lookup")
                return await original_lookup(**kwargs)

            service.repository.lock_requester_for_idempotency = (  # type: ignore[method-assign]
                _lock_requester_for_idempotency
            )
            service.repository.get_non_expired_by_idempotency_key_hash = (  # type: ignore[method-assign]
                _get_non_expired_by_idempotency_key_hash
            )

            await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                idempotency_key="lock-before-lookup",
                audit_context=AuditContext(actor_user_id=user.id),
            )

            assert calls[:2] == ["lock", "lookup"]

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


def test_idempotency_expired_key_allows_new_request(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="expired-key@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)
            now = datetime.now(UTC)
            key = "same-key-expired"
            key_hash = sha256(key.encode("utf-8")).hexdigest()

            first = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                requester_note="first",
                idempotency_key=key,
                now=now,
                audit_context=audit_context,
            )
            first.idempotency_key_expires_at = now - timedelta(seconds=1)
            await service.repository.save(first)

            second = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                requester_note="second",
                idempotency_key=key,
                now=now + timedelta(seconds=2),
                audit_context=audit_context,
            )

            assert second.id != first.id
            assert second.idempotency_key_hash == key_hash
            expected_expiry = now + timedelta(
                seconds=2, hours=service.IDEMPOTENCY_KEY_TTL_HOURS
            )
            assert (
                second.idempotency_key_expires_at.replace(tzinfo=UTC) == expected_expiry
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
            with pytest.raises(ConflictError, match="Use fulfil_request"):
                await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.FULFILLED,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )
            with pytest.raises(
                ConflictError,
                match="Execution pipeline is not implemented",
            ):
                await service.fulfil_request(
                    request_id=request.id,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )

            request = await service.transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.CANCELLED,
                reviewer_user_id=user.id,
                audit_context=audit_context,
            )
            assert request.status == DataSubjectRequestStatus.CANCELLED.value
            with pytest.raises(ConflictError):
                await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.UNDER_REVIEW,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )

    run_async(_run())


def test_state_machine_submitted_to_approved(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="submitted-approved@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            request = await service.submit_request(
                requester_user_id=user.id,
                request_type="access",
                audit_context=audit_context,
            )
            request = await service.transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.APPROVED,
                reviewer_user_id=user.id,
                audit_context=audit_context,
            )
            assert request.status == DataSubjectRequestStatus.APPROVED.value
            assert request.decided_at is not None

    run_async(_run())


def test_state_machine_rejects_direct_submitted_to_fulfilled_transition(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="submitted-fulfilled@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            request = await service.submit_request(
                requester_user_id=user.id,
                request_type="access",
                audit_context=audit_context,
            )
            with pytest.raises(ConflictError, match="Use fulfil_request"):
                await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.FULFILLED,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )

            persisted = await service.get_request(request_id=request.id)
            assert persisted.status == DataSubjectRequestStatus.SUBMITTED.value
            assert persisted.fulfilled_at is None

    run_async(_run())


def test_transition_status_rejects_execution_verified_bypass_argument(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="bypass-argument@example.com")
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            request = await service.submit_request(
                requester_user_id=user.id,
                request_type="export",
                audit_context=audit_context,
            )
            request = await service.transition_status(
                request_id=request.id,
                target_status=DataSubjectRequestStatus.APPROVED,
                reviewer_user_id=user.id,
                audit_context=audit_context,
            )

            with pytest.raises(TypeError):
                await service.transition_status(  # type: ignore[call-arg]
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.FULFILLED,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                    execution_verified=True,
                )

            persisted = await service.get_request(request_id=request.id)
            assert persisted.status == DataSubjectRequestStatus.APPROVED.value
            assert persisted.fulfilled_at is None

    run_async(_run())


@pytest.mark.parametrize(
    "terminal_status",
    [
        DataSubjectRequestStatus.REJECTED,
        DataSubjectRequestStatus.CANCELLED,
        DataSubjectRequestStatus.FULFILLED,
    ],
)
def test_terminal_states_reject_further_transitions(
    migrated_session_factory, terminal_status: DataSubjectRequestStatus
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(
                session, email=f"terminal-{terminal_status.value}@example.com"
            )
            service = DataSubjectRequestService(session)
            audit_context = AuditContext(actor_user_id=user.id)
            request = await service.submit_request(
                requester_user_id=user.id,
                request_type=(
                    "export"
                    if terminal_status is DataSubjectRequestStatus.FULFILLED
                    else "access"
                ),
                audit_context=audit_context,
            )
            if terminal_status is DataSubjectRequestStatus.REJECTED:
                request = await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.UNDER_REVIEW,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )
            if terminal_status is DataSubjectRequestStatus.FULFILLED:
                request = await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.APPROVED,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )

            if terminal_status is DataSubjectRequestStatus.FULFILLED:
                await _create_ready_export_artifact(
                    session,
                    request=request,
                    user=user,
                )
                request = await service.fulfil_request(
                    request_id=request.id,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )
            else:
                request = await service.transition_status(
                    request_id=request.id,
                    target_status=terminal_status,
                    reviewer_user_id=user.id,
                    audit_context=audit_context,
                )
            with pytest.raises(ConflictError):
                await service.transition_status(
                    request_id=request.id,
                    target_status=DataSubjectRequestStatus.UNDER_REVIEW,
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
