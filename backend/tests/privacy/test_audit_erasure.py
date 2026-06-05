from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.privacy.erasures.audit import (
    AuditErasureError,
    AuditErasureStatus,
    minimise_audit_events_for_approved_erase_request,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_user(session, *, email: str | None = None) -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email or f"subject-{uuid4()}@example.com",
        email_verified=True,
        first_name="Subject",
        last_name="User",
        onboarding_completed=True,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _dsr_for_user(
    user: User,
    *,
    request_type: str = "erase",
    status: str = DataSubjectRequestStatus.APPROVED.value,
) -> DataSubjectRequest:
    now = datetime.now(UTC)
    return DataSubjectRequest(
        request_type=request_type,
        status=status,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=now,
        reviewed_at=now if status == DataSubjectRequestStatus.APPROVED.value else None,
        decided_at=now if status == DataSubjectRequestStatus.APPROVED.value else None,
        due_at=now + timedelta(days=30),
    )


def _subject_actor_event(user: User) -> AuditEvent:
    return AuditEvent(
        actor_user_id=user.id,
        category=AuditCategory.SECURITY.value,
        action=AuditAction.USER_SUSPENDED.value,
        target_type=AuditTargetType.ORGANISATION.value,
        target_id=uuid4(),
        reason="free text mentioning the subject",
        metadata_json={"note": "possible personal data", "safe": True},
        ip_address="192.0.2.15",
        user_agent="Mozilla/5.0 subject browser",
    )


def _subject_target_event(user: User) -> AuditEvent:
    return AuditEvent(
        actor_user_id=None,
        category=AuditCategory.COMPLIANCE.value,
        action=AuditAction.DATA_SUBJECT_REQUEST_SUBMITTED.value,
        target_type=AuditTargetType.USER.value,
        target_id=user.id,
        reason="subject target reason",
        metadata_json={"requester_email": user.email},
        ip_address="198.51.100.20",
        user_agent="Subject user agent",
    )


def _unrelated_event(other_user: User) -> AuditEvent:
    return AuditEvent(
        actor_user_id=other_user.id,
        category=AuditCategory.TENANT.value,
        action=AuditAction.INVITE_CREATED.value,
        target_type=AuditTargetType.INVITE.value,
        target_id=uuid4(),
        reason="should stay untouched",
        metadata_json={"email": other_user.email},
        ip_address="203.0.113.10",
        user_agent="Other user agent",
    )


def test_audit_erasure_minimises_direct_subject_audit_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            other_user = await _create_user(session)
            dsr = _dsr_for_user(user)
            actor_event = _subject_actor_event(user)
            target_event = _subject_target_event(user)
            unrelated_event = _unrelated_event(other_user)
            session.add_all([dsr, actor_event, target_event, unrelated_event])
            await session.flush()

            result = await minimise_audit_events_for_approved_erase_request(
                session,
                dsr,
            )
            await session.refresh(actor_event)
            await session.refresh(target_event)
            await session.refresh(unrelated_event)

            assert result.provider_key == (
                "audit.minimise_subject_actor_or_target_identifiers"
            )
            assert result.table_name == "audit_events"
            assert result.subject_user_id == user.id
            assert result.status is AuditErasureStatus.MINIMISED
            assert result.affected_rows == 2
            assert result.did_mutate is True
            assert set(result.changed_fields) == {
                "actor_user_id",
                "target_id",
                "reason",
                "metadata_json",
                "ip_address",
                "user_agent",
            }
            assert actor_event.actor_user_id is None
            assert actor_event.target_id is not None
            assert actor_event.reason is None
            assert actor_event.metadata_json is None
            assert actor_event.ip_address is None
            assert actor_event.user_agent is None
            assert target_event.actor_user_id is None
            assert target_event.target_id is None
            assert target_event.reason is None
            assert target_event.metadata_json is None
            assert target_event.ip_address is None
            assert target_event.user_agent is None
            assert unrelated_event.actor_user_id == other_user.id
            assert unrelated_event.reason == "should stay untouched"
            assert unrelated_event.metadata_json == {"email": other_user.email}

    run_async(_run())


def test_audit_erasure_is_idempotent_after_minimisation(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(user)
            event = _subject_actor_event(user)
            session.add_all([dsr, event])
            await session.flush()

            first = await minimise_audit_events_for_approved_erase_request(
                session,
                dsr,
            )
            second = await minimise_audit_events_for_approved_erase_request(
                session,
                dsr,
            )

            assert first.status is AuditErasureStatus.MINIMISED
            assert second.status is AuditErasureStatus.ALREADY_MINIMISED
            assert second.affected_rows == 0
            assert second.changed_fields == ()
            assert second.did_mutate is False

    run_async(_run())


def test_audit_erasure_rejects_legal_hold_without_partial_minimisation(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(user)
            mutable_event = _subject_actor_event(user)
            held_event = _subject_target_event(user)
            held_event.legal_hold_until = datetime.now(UTC) + timedelta(days=7)
            session.add_all([dsr, mutable_event, held_event])
            await session.flush()

            with pytest.raises(AuditErasureError) as exc_info:
                await minimise_audit_events_for_approved_erase_request(
                    session,
                    dsr,
                )

            assert exc_info.value.reason_code == "audit_erasure_legal_hold_active"
            await session.refresh(mutable_event)
            await session.refresh(held_event)
            assert mutable_event.actor_user_id == user.id
            assert mutable_event.reason == "free text mentioning the subject"
            assert held_event.target_id == user.id
            assert held_event.reason == "subject target reason"

    run_async(_run())


@pytest.mark.parametrize(
    ("request_type", "status", "expected_reason"),
    [
        ("export", DataSubjectRequestStatus.APPROVED.value, "requires_erase"),
        ("erase", DataSubjectRequestStatus.SUBMITTED.value, "requires_approved"),
    ],
)
def test_audit_erasure_rejects_ineligible_requests(
    migrated_session_factory,
    request_type: str,
    status: str,
    expected_reason: str,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(user, request_type=request_type, status=status)
            session.add(dsr)
            await session.flush()

            with pytest.raises(AuditErasureError) as exc_info:
                await minimise_audit_events_for_approved_erase_request(
                    session,
                    dsr,
                )

            assert expected_reason in exc_info.value.reason_code

    run_async(_run())


def test_audit_erasure_rejects_missing_subject(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            dsr = DataSubjectRequest(
                request_type="erase",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=uuid4(),
                subject_user_id=uuid4(),
                submitted_at=now,
                reviewed_at=now,
                decided_at=now,
                due_at=now + timedelta(days=30),
            )
            session.add(dsr)
            await session.flush()

            with pytest.raises(AuditErasureError) as exc_info:
                await minimise_audit_events_for_approved_erase_request(
                    session,
                    dsr,
                )

            assert exc_info.value.reason_code == "audit_erasure_subject_not_found"

    run_async(_run())
