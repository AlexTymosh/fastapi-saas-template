from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.privacy.erasures.outbox import (
    OutboxErasureError,
    OutboxErasureStatus,
    scrub_outbox_for_approved_erase_request,
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
        email=email,
        email_verified=email is not None,
        first_name="Subject",
        last_name="User",
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


def _invite_payload(
    *,
    invite_id: UUID,
    email: str,
    extra_note: str = "free text with possible PII",
) -> dict[str, object]:
    return {
        "invite_id": str(invite_id),
        "organisation_id": str(uuid4()),
        "email": email,
        "encrypted_raw_token": "encrypted-secret-token",
        "purpose": "created",
        "role": "member",
        "debug_note": extra_note,
    }


def test_outbox_erasure_scrubs_subject_payloads_and_terminalises_pending(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            subject_email = f"MixedCase-{uuid4()}@Example.COM"
            user = await _create_user(session, email=subject_email)
            dsr = _dsr_for_user(user)
            invite_id = uuid4()
            unrelated_invite_id = uuid4()
            now = datetime.now(UTC)

            pending_by_invite = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite_id,
                payload_json=_invite_payload(
                    invite_id=invite_id,
                    email=subject_email.lower(),
                ),
                status=OutboxStatus.PENDING.value,
                next_attempt_at=now + timedelta(minutes=5),
            )
            processed_by_payload_email = OutboxEvent(
                event_type=OutboxEventType.INVITE_RESEND.value,
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json=_invite_payload(
                    invite_id=uuid4(),
                    email=f"  {subject_email.lower()}  ",
                ),
                status=OutboxStatus.PROCESSED.value,
                last_error="old free-text error with possible PII",
            )
            unrelated = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=unrelated_invite_id,
                payload_json=_invite_payload(
                    invite_id=unrelated_invite_id,
                    email=f"other-{uuid4()}@example.com",
                ),
                status=OutboxStatus.PENDING.value,
            )
            session.add_all(
                [dsr, pending_by_invite, processed_by_payload_email, unrelated]
            )
            await session.flush()

            result = await scrub_outbox_for_approved_erase_request(
                session,
                dsr,
                invite_ids=(invite_id,),
            )
            await session.refresh(pending_by_invite)
            await session.refresh(processed_by_payload_email)
            await session.refresh(unrelated)

            assert result.provider_key == "outbox.purge_or_scrub_payload"
            assert result.table_name == "outbox_events"
            assert result.status is OutboxErasureStatus.SCRUBBED
            assert result.affected_rows == 2
            assert result.did_mutate is True
            assert set(result.changed_fields) >= {"payload_json", "last_error"}

            assert pending_by_invite.status == OutboxStatus.FAILED.value
            assert pending_by_invite.next_attempt_at is None
            assert pending_by_invite.locked_at is None
            assert pending_by_invite.last_error == "privacy_erasure_scrubbed"
            assert pending_by_invite.payload_json == {
                "invite_id": str(invite_id),
                "organisation_id": pending_by_invite.payload_json["organisation_id"],
                "purpose": "created",
                "role": "member",
                "sensitive_payload_scrubbed": True,
                "privacy_erasure_scrubbed": True,
            }
            assert "email" not in pending_by_invite.payload_json
            assert "encrypted_raw_token" not in pending_by_invite.payload_json
            assert "debug_note" not in pending_by_invite.payload_json

            assert processed_by_payload_email.status == OutboxStatus.PROCESSED.value
            assert processed_by_payload_email.last_error is None
            assert "email" not in processed_by_payload_email.payload_json
            assert "encrypted_raw_token" not in processed_by_payload_email.payload_json
            assert unrelated.status == OutboxStatus.PENDING.value
            assert "email" in unrelated.payload_json
            assert "encrypted_raw_token" in unrelated.payload_json

    run_async(_run())


def test_outbox_erasure_uses_snapshots_after_subject_profile_is_anonymised(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            original_email = f"Snapshot-{uuid4()}@Example.COM"
            user = await _create_user(session, email=None)
            dsr = _dsr_for_user(user)
            invite_id = uuid4()
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite_id,
                payload_json=_invite_payload(
                    invite_id=invite_id,
                    email=original_email.lower(),
                ),
                status=OutboxStatus.PENDING.value,
            )
            session.add_all([dsr, event])
            await session.flush()

            result = await scrub_outbox_for_approved_erase_request(
                session,
                dsr,
                subject_email=original_email,
                invite_ids=(invite_id,),
            )
            await session.refresh(event)

            assert result.affected_rows == 1
            assert event.status == OutboxStatus.FAILED.value
            assert "email" not in event.payload_json
            assert "encrypted_raw_token" not in event.payload_json

    run_async(_run())


def test_outbox_erasure_is_idempotent_with_invite_id_snapshot(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=f"subject-{uuid4()}@example.com")
            dsr = _dsr_for_user(user)
            invite_id = uuid4()
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite_id,
                payload_json=_invite_payload(invite_id=invite_id, email=user.email),
                status=OutboxStatus.PENDING.value,
            )
            session.add_all([dsr, event])
            await session.flush()

            first_result = await scrub_outbox_for_approved_erase_request(
                session,
                dsr,
                invite_ids=(invite_id,),
            )
            second_result = await scrub_outbox_for_approved_erase_request(
                session,
                dsr,
                invite_ids=(invite_id,),
            )

            assert first_result.affected_rows == 1
            assert second_result.status is OutboxErasureStatus.ALREADY_SCRUBBED
            assert second_result.affected_rows == 0
            assert second_result.changed_fields == ()
            assert second_result.did_mutate is False

    run_async(_run())


@pytest.mark.parametrize(
    ("request_type", "status", "expected_reason"),
    [
        ("export", DataSubjectRequestStatus.APPROVED.value, "requires_erase"),
        ("erase", DataSubjectRequestStatus.SUBMITTED.value, "requires_approved"),
    ],
)
def test_outbox_erasure_rejects_ineligible_requests(
    migrated_session_factory,
    request_type: str,
    status: str,
    expected_reason: str,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=f"subject-{uuid4()}@example.com")
            dsr = _dsr_for_user(user, request_type=request_type, status=status)
            session.add(dsr)
            await session.flush()

            with pytest.raises(OutboxErasureError) as exc_info:
                await scrub_outbox_for_approved_erase_request(session, dsr)

            assert expected_reason in exc_info.value.reason_code

    run_async(_run())


def test_outbox_erasure_rejects_subjectless_request(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        now = datetime.now(UTC)
        dsr = DataSubjectRequest(
            request_type="erase",
            status=DataSubjectRequestStatus.APPROVED.value,
            requester_user_id=uuid4(),
            subject_user_id=None,
            submitted_at=now,
            due_at=now + timedelta(days=30),
        )

        async with migrated_session_factory() as session:
            with pytest.raises(OutboxErasureError) as exc_info:
                await scrub_outbox_for_approved_erase_request(session, dsr)

            assert "requires_subject_user" in exc_info.value.reason_code

    run_async(_run())


def test_outbox_erasure_rejects_missing_subject_user(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        now = datetime.now(UTC)
        dsr = DataSubjectRequest(
            request_type="erase",
            status=DataSubjectRequestStatus.APPROVED.value,
            requester_user_id=uuid4(),
            subject_user_id=uuid4(),
            submitted_at=now,
            due_at=now + timedelta(days=30),
        )

        async with migrated_session_factory() as session:
            with pytest.raises(OutboxErasureError) as exc_info:
                await scrub_outbox_for_approved_erase_request(session, dsr)

            assert "subject_not_found" in exc_info.value.reason_code

    run_async(_run())
