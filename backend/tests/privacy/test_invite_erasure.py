from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.invites.anonymisation import (
    scrubbed_invite_email,
    scrubbed_invite_token_hash,
)
from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
from app.privacy.erasures.invite import (
    InviteErasureError,
    InviteErasureStatus,
    anonymise_invites_for_approved_erase_request,
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
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_organisation(session) -> Organisation:
    organisation = Organisation(name="Invite Erasure Org", slug=f"org-{uuid4()}")
    session.add(organisation)
    await session.flush()
    await session.refresh(organisation)
    return organisation


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


def _invite(
    *,
    email: str,
    organisation_id,
    status: InviteStatus = InviteStatus.PENDING,
    revoked_by_user_id=None,
    revoked_at: datetime | None = None,
) -> Invite:
    return Invite(
        email=email,
        organisation_id=organisation_id,
        role=MembershipRole.MEMBER,
        status=status,
        token_hash=f"token-{uuid4()}",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_by_user_id=revoked_by_user_id,
        revoked_at=revoked_at,
    )


def test_invite_erasure_anonymises_invitee_and_revoker_references(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email="Subject.User@Example.COM")
            other_user = await _create_user(session)
            organisation = await _create_organisation(session)
            now = datetime.now(UTC)
            invitee_invite = _invite(
                email="subject.user@example.com",
                organisation_id=organisation.id,
            )
            revoker_invite = _invite(
                email=other_user.email,
                organisation_id=organisation.id,
                status=InviteStatus.REVOKED,
                revoked_by_user_id=user.id,
                revoked_at=now,
            )
            unrelated_invite = _invite(
                email=other_user.email,
                organisation_id=organisation.id,
            )
            dsr = _dsr_for_user(user)
            session.add_all([invitee_invite, revoker_invite, unrelated_invite, dsr])
            await session.flush()

            result = await anonymise_invites_for_approved_erase_request(
                session,
                dsr,
            )
            await session.refresh(invitee_invite)
            await session.refresh(revoker_invite)
            await session.refresh(unrelated_invite)

            assert result.provider_key == (
                "invites.anonymise_or_purge_subject_references"
            )
            assert result.table_name == "invites"
            assert result.subject_user_id == user.id
            assert result.status is InviteErasureStatus.ANONYMISED
            assert result.affected_rows == 2
            assert result.did_mutate is True
            assert set(result.changed_fields) == {
                "email",
                "token_hash",
                "expires_at",
                "status",
                "revoked_at",
                "revoked_by_user_id",
            }

            assert invitee_invite.email == scrubbed_invite_email(invitee_invite.id)
            assert invitee_invite.token_hash == scrubbed_invite_token_hash(
                invitee_invite.id
            )
            assert invitee_invite.expires_at is None
            assert invitee_invite.status == InviteStatus.REVOKED
            assert invitee_invite.revoked_at is not None
            assert invitee_invite.revoked_by_user_id is None

            assert revoker_invite.email == other_user.email
            assert revoker_invite.token_hash.startswith("token-")
            assert revoker_invite.revoked_by_user_id is None

            assert unrelated_invite.email == other_user.email
            assert unrelated_invite.token_hash.startswith("token-")

    run_async(_run())


def test_invite_erasure_can_use_subject_email_snapshot_after_profile_erasure(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=None)
            organisation = await _create_organisation(session)
            invite = _invite(
                email="subject.snapshot@example.com",
                organisation_id=organisation.id,
            )
            dsr = _dsr_for_user(user)
            session.add_all([invite, dsr])
            await session.flush()

            result = await anonymise_invites_for_approved_erase_request(
                session,
                dsr,
                subject_email="Subject.Snapshot@Example.COM",
            )
            await session.refresh(invite)

            assert result.affected_rows == 1
            assert invite.email == scrubbed_invite_email(invite.id)
            assert invite.token_hash == scrubbed_invite_token_hash(invite.id)

    run_async(_run())


def test_invite_erasure_is_idempotent(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            organisation = await _create_organisation(session)
            invite = _invite(email=user.email, organisation_id=organisation.id)
            dsr = _dsr_for_user(user)
            session.add_all([invite, dsr])
            await session.flush()

            first_result = await anonymise_invites_for_approved_erase_request(
                session,
                dsr,
            )
            second_result = await anonymise_invites_for_approved_erase_request(
                session,
                dsr,
            )

            assert first_result.affected_rows == 1
            assert second_result.status is InviteErasureStatus.ALREADY_ANONYMISED
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
def test_invite_erasure_rejects_ineligible_requests(
    migrated_session_factory,
    request_type: str,
    status: str,
    expected_reason: str,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            organisation = await _create_organisation(session)
            invite = _invite(email=user.email, organisation_id=organisation.id)
            dsr = _dsr_for_user(user, request_type=request_type, status=status)
            session.add_all([invite, dsr])
            await session.flush()

            with pytest.raises(InviteErasureError) as exc_info:
                await anonymise_invites_for_approved_erase_request(session, dsr)

            assert expected_reason in exc_info.value.reason_code
            await session.refresh(invite)
            assert invite.email == user.email
            assert invite.token_hash.startswith("token-")

    run_async(_run())


def test_invite_erasure_rejects_subjectless_request(
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
            with pytest.raises(InviteErasureError) as exc_info:
                await anonymise_invites_for_approved_erase_request(session, dsr)

            assert "requires_subject_user" in exc_info.value.reason_code

    run_async(_run())


def test_invite_erasure_rejects_missing_subject_user(
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
            with pytest.raises(InviteErasureError) as exc_info:
                await anonymise_invites_for_approved_erase_request(session, dsr)

            assert "subject_not_found" in exc_info.value.reason_code

    run_async(_run())
