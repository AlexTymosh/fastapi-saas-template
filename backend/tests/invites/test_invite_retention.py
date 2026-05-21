from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.invites.models.invite import Invite, InviteStatus
from app.invites.services.invites import InviteService
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
from tests.helpers.asyncio_runner import run_async


def test_invite_retention_anonymises_only_old_completed_invites(
    migrated_session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INVITE_RETENTION__ACCEPTED_DAYS", "30")
    monkeypatch.setenv("INVITE_RETENTION__EXPIRED_DAYS", "30")
    monkeypatch.setenv("INVITE_RETENTION__REVOKED_DAYS", "30")
    monkeypatch.setenv("INVITE_RETENTION__BATCH_SIZE", "10")

    now = datetime(2026, 5, 21, tzinfo=UTC)
    old = now - timedelta(days=31)
    recent = now - timedelta(days=2)

    async def scenario() -> None:
        async with migrated_session_factory() as session:
            organisation = Organisation(
                name="Retention Clinic",
                slug="retention-clinic",
            )
            session.add(organisation)
            await session.flush()

            old_accepted = Invite(
                email="old.accepted@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.ACCEPTED,
                token_hash="old-accepted-token-hash",
                expires_at=old,
                updated_at=old,
            )
            old_expired = Invite(
                email="old.expired@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.EXPIRED,
                token_hash="old-expired-token-hash",
                expires_at=old,
                updated_at=old,
            )
            old_revoked = Invite(
                email="old.revoked@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.REVOKED,
                token_hash="old-revoked-token-hash",
                expires_at=old,
                revoked_at=old,
                updated_at=old,
            )
            recent_accepted = Invite(
                email="recent.accepted@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.ACCEPTED,
                token_hash="recent-accepted-token-hash",
                expires_at=recent,
                updated_at=recent,
            )
            pending = Invite(
                email="pending@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash="pending-token-hash",
                expires_at=old,
                updated_at=old,
            )
            session.add_all(
                [old_accepted, old_expired, old_revoked, recent_accepted, pending]
            )
            await session.commit()

            anonymised_count = await InviteService(session).anonymise_completed_invites(
                now=now
            )
            assert anonymised_count == 3

            rows = (
                (await session.execute(select(Invite).order_by(Invite.email)))
                .scalars()
                .all()
            )
            by_id = {row.id: row for row in rows}

            for invite in (old_accepted, old_expired, old_revoked):
                refreshed = by_id[invite.id]
                assert refreshed.email.endswith("@anonymous.invalid")
                assert str(refreshed.id) in refreshed.email
                assert refreshed.token_hash == f"scrubbed-invite:{refreshed.id}"

            assert by_id[recent_accepted.id].email == "recent.accepted@example.com"
            assert by_id[recent_accepted.id].token_hash == "recent-accepted-token-hash"
            assert by_id[pending.id].email == "pending@example.com"
            assert by_id[pending.id].token_hash == "pending-token-hash"

    run_async(scenario())


def test_invite_retention_is_idempotent(migrated_session_factory, monkeypatch) -> None:
    monkeypatch.setenv("INVITE_RETENTION__ACCEPTED_DAYS", "30")
    monkeypatch.setenv("INVITE_RETENTION__BATCH_SIZE", "10")

    now = datetime(2026, 5, 21, tzinfo=UTC)
    old = now - timedelta(days=31)

    async def scenario() -> None:
        async with migrated_session_factory() as session:
            organisation = Organisation(
                name="Retention Clinic",
                slug="retention-clinic",
            )
            session.add(organisation)
            await session.flush()
            invite = Invite(
                email="old.accepted@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.ACCEPTED,
                token_hash="old-accepted-token-hash",
                expires_at=old,
                updated_at=old,
            )
            session.add(invite)
            await session.commit()

            first_count = await InviteService(session).anonymise_completed_invites(
                now=now
            )
            second_count = await InviteService(session).anonymise_completed_invites(
                now=now
            )

            await session.refresh(invite)
            assert first_count == 1
            assert second_count == 0
            assert invite.email == f"deleted-invite-{invite.id}@anonymous.invalid"
            assert invite.token_hash == f"scrubbed-invite:{invite.id}"

    run_async(scenario())


def test_invite_retention_excludes_scrubbed_rows_from_limited_batch(
    migrated_session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INVITE_RETENTION__ACCEPTED_DAYS", "30")
    monkeypatch.setenv("INVITE_RETENTION__BATCH_SIZE", "1")

    now = datetime(2026, 5, 21, tzinfo=UTC)
    very_old = now - timedelta(days=60)
    old = now - timedelta(days=31)

    async def scenario() -> None:
        async with migrated_session_factory() as session:
            organisation = Organisation(
                name="Retention Clinic",
                slug="retention-clinic",
            )
            session.add(organisation)
            await session.flush()

            scrubbed_id = uuid4()
            unsanitized_id = uuid4()
            already_scrubbed = Invite(
                id=scrubbed_id,
                email=f"deleted-invite-{scrubbed_id}@anonymous.invalid",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.ACCEPTED,
                token_hash=f"scrubbed-invite:{scrubbed_id}",
                expires_at=very_old,
                updated_at=very_old,
            )
            unsanitized = Invite(
                id=unsanitized_id,
                email="later.unsanitized@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.ACCEPTED,
                token_hash="later-unsanitized-token-hash",
                expires_at=old,
                updated_at=old,
            )
            session.add_all([already_scrubbed, unsanitized])
            await session.commit()

            anonymised_count = await InviteService(session).anonymise_completed_invites(
                now=now
            )

            assert anonymised_count == 1
            await session.refresh(already_scrubbed)
            await session.refresh(unsanitized)
            assert already_scrubbed.email == (
                f"deleted-invite-{scrubbed_id}@anonymous.invalid"
            )
            assert already_scrubbed.token_hash == f"scrubbed-invite:{scrubbed_id}"
            assert unsanitized.email == (
                f"deleted-invite-{unsanitized_id}@anonymous.invalid"
            )
            assert unsanitized.token_hash == f"scrubbed-invite:{unsanitized_id}"

    run_async(scenario())
