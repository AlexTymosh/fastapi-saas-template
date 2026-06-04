from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.privacy.erasures.user_profile import (
    UserProfileErasureError,
    UserProfileErasureStatus,
    anonymise_user_profile_for_approved_erase_request,
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
        suspended_reason="Free-text note that may contain personal data",
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


def test_user_profile_erasure_anonymises_direct_identifiers(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(
                session,
                email=f"MixedCase-{uuid4()}@Example.COM",
            )
            dsr = _dsr_for_user(user)
            session.add(dsr)
            await session.flush()

            result = await anonymise_user_profile_for_approved_erase_request(
                session,
                dsr,
            )
            await session.refresh(user)

            assert result.provider_key == "users.anonymise_profile"
            assert result.table_name == "users"
            assert result.subject_user_id == user.id
            assert result.status is UserProfileErasureStatus.ANONYMISED
            assert result.affected_rows == 1
            assert result.did_mutate is True
            assert set(result.changed_fields) == {
                "external_auth_id",
                "email",
                "email_verified",
                "first_name",
                "last_name",
                "onboarding_completed",
                "suspended_reason",
            }
            assert user.external_auth_id == f"erased-user:{user.id}"
            assert user.email is None
            assert user.email_verified is False
            assert user.first_name is None
            assert user.last_name is None
            assert user.onboarding_completed is False
            assert user.suspended_reason is None

    run_async(_run())


def test_user_profile_erasure_is_idempotent(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            dsr = _dsr_for_user(user)
            session.add(dsr)
            await session.flush()

            first_result = await anonymise_user_profile_for_approved_erase_request(
                session,
                dsr,
            )
            second_result = await anonymise_user_profile_for_approved_erase_request(
                session,
                dsr,
            )

            assert first_result.affected_rows == 1
            assert second_result.status is UserProfileErasureStatus.ALREADY_ANONYMISED
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
def test_user_profile_erasure_rejects_ineligible_requests(
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

            with pytest.raises(UserProfileErasureError) as exc_info:
                await anonymise_user_profile_for_approved_erase_request(
                    session,
                    dsr,
                )

            assert expected_reason in exc_info.value.reason_code
            await session.refresh(user)
            assert user.email is not None
            assert user.external_auth_id.startswith("kc|")

    run_async(_run())


def test_user_profile_erasure_rejects_subjectless_request(
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
            with pytest.raises(UserProfileErasureError) as exc_info:
                await anonymise_user_profile_for_approved_erase_request(
                    session,
                    dsr,
                )

            assert "requires_subject_user" in exc_info.value.reason_code

    run_async(_run())


def test_user_profile_erasure_rejects_missing_subject_user(
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
            with pytest.raises(UserProfileErasureError) as exc_info:
                await anonymise_user_profile_for_approved_erase_request(
                    session,
                    dsr,
                )

            assert "subject_not_found" in exc_info.value.reason_code

    run_async(_run())
