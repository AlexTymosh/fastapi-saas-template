from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from app.invites.models.invite import Invite, InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
from tests.helpers.asyncio_runner import run_async


def test_accept_pending_invite_by_token_hash_is_atomic(
    migrated_session_factory,
) -> None:
    raw_token = "atomic-accept-token"
    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()

    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                organisation = Organisation(name="Repo Atomic", slug="repo-atomic")
                session.add(organisation)
                await session.flush()
                invite = Invite(
                    email="repo-invitee@example.com",
                    organisation_id=organisation.id,
                    role=MembershipRole.MEMBER,
                    status=InviteStatus.PENDING,
                    token_hash=token_hash,
                    expires_at=datetime.now(UTC) + timedelta(minutes=30),
                )
                session.add(invite)

            async with session.begin():
                repo = InviteRepository(session)
                first = await repo.accept_pending_invite_by_token_hash(
                    token_hash=token_hash,
                    now=datetime.now(UTC),
                )
                second = await repo.accept_pending_invite_by_token_hash(
                    token_hash=token_hash,
                    now=datetime.now(UTC),
                )
                assert first is not None
                assert second is None

            saved = await session.get(Invite, invite.id)
            assert saved is not None
            assert saved.status == InviteStatus.ACCEPTED

    run_async(_run())
