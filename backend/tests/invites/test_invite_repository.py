from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from app.invites.models.invite import Invite, InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
from tests.helpers.asyncio_runner import run_async


def test_accept_pending_invite_by_token_hash_is_atomic(
    migrated_session_factory,
) -> None:
    raw_token = "repository-atomic-token"
    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(UTC)

    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                organisation = Organisation(
                    id=uuid4(), name="Repo Atomic Org", slug="repo-atomic-org"
                )
                session.add(organisation)
                invite = Invite(
                    organisation_id=organisation.id,
                    email="repo-atomic@example.com",
                    role=MembershipRole.MEMBER,
                    status=InviteStatus.PENDING,
                    token_hash=token_hash,
                    expires_at=now + timedelta(minutes=30),
                )
                session.add(invite)

            first = await InviteRepository(session).accept_pending_invite_by_token_hash(
                token_hash=token_hash,
                now=now,
            )
            second = await InviteRepository(
                session
            ).accept_pending_invite_by_token_hash(
                token_hash=token_hash, now=now + timedelta(seconds=1)
            )
            await session.commit()

        assert first is not None
        assert second is None

        async with migrated_session_factory() as session:
            stored = await InviteRepository(session).get_by_token_hash(token_hash)
            assert stored is not None
            assert stored.status == InviteStatus.ACCEPTED

    run_async(_run())
