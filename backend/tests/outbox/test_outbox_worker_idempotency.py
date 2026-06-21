from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.outbox.models.outbox_event import (
    OutboxDeliveryClaim,
    OutboxEvent,
    OutboxEventType,
    OutboxStatus,
)
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.services.payload_crypto import OutboxPayloadCrypto
from app.outbox.workers import _process_outbox_event
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security]


class _BlockingInviteTokenSink:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.deliveries: list[tuple[str, str]] = []

    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        self.deliveries.append((invite.email, raw_token))
        self.started.set()
        await self.release.wait()


def test_duplicate_processing_jobs_deliver_invite_once(
    migrated_session_factory,
    monkeypatch,
) -> None:
    sink = _BlockingInviteTokenSink()
    monkeypatch.setattr("app.outbox.workers.get_invite_token_sink", lambda: sink)
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        raw_token = "single-delivery-token"
        crypto = OutboxPayloadCrypto.from_settings(settings=get_settings())
        encrypted_token = crypto.encrypt_token(raw_token)
        invite_id = UUID("00000000-0000-0000-0000-000000000421")

        async with migrated_session_factory() as session:
            session.add(
                Invite(
                    id=invite_id,
                    email="duplicate-worker@example.com",
                    organisation_id=UUID("00000000-0000-0000-0000-000000000001"),
                    role=MembershipRole.MEMBER,
                    status=InviteStatus.PENDING,
                    token_hash=sha256(raw_token.encode("utf-8")).hexdigest(),
                )
            )
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite_id,
                payload_json={
                    "invite_id": str(invite_id),
                    "encrypted_raw_token": encrypted_token,
                },
                status=OutboxStatus.PROCESSING.value,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        first_worker = asyncio.create_task(_process_outbox_event(event_id))
        await asyncio.wait_for(sink.started.wait(), timeout=1)

        second_worker = asyncio.create_task(_process_outbox_event(event_id))
        await asyncio.wait_for(second_worker, timeout=1)
        assert sink.deliveries == [("duplicate-worker@example.com", raw_token)]

        sink.release.set()
        await asyncio.wait_for(first_worker, timeout=1)

        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved is not None
            assert saved.status == OutboxStatus.PROCESSED.value
            assert saved.locked_at is None
            assert saved.last_error is None
            assert "encrypted_raw_token" not in saved.payload_json
            assert saved.payload_json["sensitive_payload_scrubbed"] is True

            result = await session.execute(select(OutboxDeliveryClaim))
            claims = list(result.scalars())
            assert claims == []

    run_async(_run())


def test_stale_processing_recovery_clears_delivery_claim(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        stale_time = datetime.now(UTC) - timedelta(seconds=1000)
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "encrypted_raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000422"),
                status=OutboxStatus.PROCESSING.value,
                locked_at=stale_time,
                max_attempts=2,
            )
            session.add(event)
            await session.flush()
            event_id = event.id
            session.add(
                OutboxDeliveryClaim(
                    event_id=event_id,
                    claim_token="stale-worker-claim",
                    claimed_at=stale_time,
                )
            )
            await session.commit()

        async with migrated_session_factory() as session:
            async with session.begin():
                recovered = await OutboxEventRepository(
                    session
                ).recover_stale_processing_events(
                    stale_timeout_seconds=300,
                    limit=10,
                )
                assert len(recovered) == 1

        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(event_id)
            assert saved is not None
            assert saved.status == OutboxStatus.PENDING.value
            assert saved.locked_at is None
            assert saved.last_error == "stale_processing_recovered"
            assert saved.attempts == 1

            result = await session.execute(select(OutboxDeliveryClaim))
            claims = list(result.scalars())
            assert claims == []

    run_async(_run())
