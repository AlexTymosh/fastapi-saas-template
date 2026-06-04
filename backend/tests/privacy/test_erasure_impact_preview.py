from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType
from app.privacy.erasures.impact import (
    ErasureImpactPreviewError,
    ErasureImpactScope,
    build_erasure_impact_preview,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


async def _create_user(session, *, email: str | None) -> User:
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


async def _create_organisation(session) -> Organisation:
    organisation = Organisation(name="Privacy Org", slug=f"org-{uuid4()}")
    session.add(organisation)
    await session.flush()
    await session.refresh(organisation)
    return organisation


def _approved_erase_request(user: User) -> DataSubjectRequest:
    now = datetime.now(UTC)
    return DataSubjectRequest(
        request_type="erase",
        status=DataSubjectRequestStatus.APPROVED.value,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=now,
        reviewed_at=now,
        decided_at=now,
        due_at=now + timedelta(days=30),
    )


def _impact_by_provider(preview):
    return {entry.provider_key: entry for entry in preview.entries}


def test_erasure_impact_preview_counts_user_invite_and_outbox_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=f"subject-{uuid4()}@example.com")
            other_user = await _create_user(
                session, email=f"other-{uuid4()}@example.com"
            )
            organisation = await _create_organisation(session)
            now = datetime.now(UTC)

            invite_by_email = Invite(
                email=user.email,
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash=f"token-{uuid4()}",
                expires_at=now + timedelta(days=1),
            )
            invite_by_revoker = Invite(
                email=f"external-{uuid4()}@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.REVOKED,
                token_hash=f"token-{uuid4()}",
                revoked_by_user_id=user.id,
                revoked_at=now,
            )
            unrelated_invite = Invite(
                email=other_user.email,
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash=f"token-{uuid4()}",
                expires_at=now + timedelta(days=1),
            )
            dsr = _approved_erase_request(user)
            session.add_all([invite_by_email, invite_by_revoker, unrelated_invite, dsr])
            await session.flush()

            session.add_all(
                [
                    OutboxEvent(
                        event_type=OutboxEventType.INVITE_CREATED.value,
                        aggregate_type="invite",
                        aggregate_id=invite_by_email.id,
                        payload_json={"email": user.email},
                    ),
                    OutboxEvent(
                        event_type=OutboxEventType.INVITE_RESEND.value,
                        aggregate_type="invite",
                        aggregate_id=uuid4(),
                        payload_json={"email": user.email},
                    ),
                    OutboxEvent(
                        event_type=OutboxEventType.INVITE_CREATED.value,
                        aggregate_type="invite",
                        aggregate_id=unrelated_invite.id,
                        payload_json={"email": other_user.email},
                    ),
                ]
            )
            await session.flush()

            preview = await build_erasure_impact_preview(session, dsr)
            by_provider = _impact_by_provider(preview)

            assert by_provider["users.anonymise_profile"].estimated_rows == 1
            assert (
                by_provider[
                    "invites.anonymise_or_purge_subject_references"
                ].estimated_rows
                == 2
            )
            assert by_provider["outbox.purge_or_scrub_payload"].estimated_rows == 2
            assert by_provider["users.anonymise_profile"].is_scoped is True
            assert preview.total_scoped_rows == 5
            assert set(preview.scoped_provider_keys) == {
                "users.anonymise_profile",
                "invites.anonymise_or_purge_subject_references",
                "outbox.purge_or_scrub_payload",
            }

    run_async(_run())


def test_erasure_impact_preview_normalises_subject_email_for_outbox_payload(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            raw_email = f" Subject-{uuid4()}@Example.COM "
            user = await _create_user(session, email=raw_email)
            dsr = _approved_erase_request(user)
            session.add(dsr)
            await session.flush()

            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.INVITE_RESEND.value,
                    aggregate_type="invite",
                    aggregate_id=uuid4(),
                    payload_json={"email": raw_email.strip().lower()},
                )
            )
            await session.flush()

            preview = await build_erasure_impact_preview(session, dsr)
            by_provider = _impact_by_provider(preview)

            assert (
                by_provider[
                    "invites.anonymise_or_purge_subject_references"
                ].estimated_rows
                == 0
            )
            assert by_provider["outbox.purge_or_scrub_payload"].estimated_rows == 1
            assert preview.total_scoped_rows == 2

    run_async(_run())


def test_erasure_impact_preview_handles_subject_without_email(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=None)
            organisation = await _create_organisation(session)
            invite = Invite(
                email=f"external-{uuid4()}@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.REVOKED,
                token_hash=f"token-{uuid4()}",
                revoked_by_user_id=user.id,
                revoked_at=datetime.now(UTC),
            )
            dsr = _approved_erase_request(user)
            session.add_all([invite, dsr])
            await session.flush()
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.INVITE_CREATED.value,
                    aggregate_type="invite",
                    aggregate_id=invite.id,
                    payload_json={"email": "external@example.com"},
                )
            )
            await session.flush()

            preview = await build_erasure_impact_preview(session, dsr)
            by_provider = _impact_by_provider(preview)

            assert by_provider["users.anonymise_profile"].estimated_rows == 1
            assert (
                by_provider[
                    "invites.anonymise_or_purge_subject_references"
                ].estimated_rows
                == 1
            )
            assert by_provider["outbox.purge_or_scrub_payload"].estimated_rows == 1

    run_async(_run())


@pytest.mark.parametrize(
    ("request_type", "status", "expected_reason"),
    [
        ("export", DataSubjectRequestStatus.APPROVED.value, "requires_erase"),
        ("erase", DataSubjectRequestStatus.SUBMITTED.value, "requires_approved"),
    ],
)
def test_erasure_impact_preview_rejects_ineligible_requests(
    migrated_session_factory,
    request_type: str,
    status: str,
    expected_reason: str,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=f"subject-{uuid4()}@example.com")
            now = datetime.now(UTC)
            dsr = DataSubjectRequest(
                request_type=request_type,
                status=status,
                requester_user_id=user.id,
                subject_user_id=user.id,
                submitted_at=now,
                due_at=now + timedelta(days=30),
            )
            session.add(dsr)
            await session.flush()

            with pytest.raises(ErasureImpactPreviewError) as exc_info:
                await build_erasure_impact_preview(session, dsr)

            assert expected_reason in exc_info.value.reason_code

    run_async(_run())


def test_erasure_impact_preview_marks_unscoped_providers(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session, email=f"subject-{uuid4()}@example.com")
            dsr = _approved_erase_request(user)
            session.add(dsr)
            await session.flush()

            preview = await build_erasure_impact_preview(session, dsr)
            unscoped_entries = [
                entry
                for entry in preview.entries
                if entry.impact_scope is ErasureImpactScope.NOT_SCOPED_YET
            ]

            assert unscoped_entries
            assert all(entry.estimated_rows is None for entry in unscoped_entries)
            assert set(preview.unscoped_provider_keys) == {
                entry.provider_key for entry in unscoped_entries
            }

    run_async(_run())
