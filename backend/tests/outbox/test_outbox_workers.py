from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.outbox.workers import process_outbox_event


class CaptureSink:
    def __init__(self) -> None:
        self.deliveries = 0

    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        self.deliveries += 1


@pytest.mark.asyncio
async def test_process_outbox_event_marks_event_processed(
    migrated_session_factory, monkeypatch
) -> None:
    from app.outbox import workers

    sink = CaptureSink()
    monkeypatch.setattr(workers, "get_invite_token_sink", lambda: sink)

    raw_token = "token-123"
    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()

    async with migrated_session_factory() as session:
        async with session.begin():
            invite = Invite(
                email="outbox@example.com",
                organisation_id=uuid4(),
                role=MembershipRole.MEMBER,
                token_hash=token_hash,
                status=InviteStatus.PENDING,
            )
            session.add(invite)
            await session.flush()
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json={"invite_id": str(invite.id), "raw_token": raw_token},
            )
            session.add(event)
            await session.flush()
            event_id = str(event.id)

    await process_outbox_event.fn(event_id)

    async with migrated_session_factory() as session:
        result = await session.execute(
            select(OutboxEvent).where(OutboxEvent.id == UUID(event_id))
        )
        event = result.scalar_one()
        assert event.status == OutboxStatus.PROCESSED.value
        assert event.processed_at is not None
        assert sink.deliveries == 1


@pytest.mark.asyncio
async def test_process_outbox_event_persists_failure_state(
    migrated_session_factory, monkeypatch
) -> None:
    from app.outbox import workers

    class FailingSink:
        async def deliver(self, *, invite: Invite, raw_token: str) -> None:
            raise RuntimeError("delivery down")

    monkeypatch.setattr(workers, "get_invite_token_sink", lambda: FailingSink())

    raw_token = "token-err"
    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()

    async with migrated_session_factory() as session:
        async with session.begin():
            invite = Invite(
                email="fail@example.com",
                organisation_id=uuid4(),
                role=MembershipRole.MEMBER,
                token_hash=token_hash,
                status=InviteStatus.PENDING,
            )
            session.add(invite)
            await session.flush()
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_RESEND.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json={"invite_id": str(invite.id), "raw_token": raw_token},
                max_attempts=1,
            )
            session.add(event)
            await session.flush()
            event_id = str(event.id)

    with pytest.raises(RuntimeError):
        await process_outbox_event.fn(event_id)

    async with migrated_session_factory() as session:
        result = await session.execute(
            select(OutboxEvent).where(OutboxEvent.id == UUID(event_id))
        )
        event = result.scalar_one()
        assert event.attempts == 1
        assert event.status == OutboxStatus.FAILED.value
        assert event.last_error == "delivery_failed:RuntimeError"
        assert "token-err" not in (event.last_error or "")
