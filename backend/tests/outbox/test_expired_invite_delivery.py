from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import select

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.services.payload_crypto import OutboxPayloadCrypto
from app.outbox.workers import _process_outbox_event
from tests.helpers.asyncio_runner import run_async
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security]


def test_worker_expires_pending_invite_before_delivery(
    migrated_session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )
    monkeypatch.setenv("APP__ENVIRONMENT", "test")
    reset_settings_cache()

    class _MustNotCallSink:
        async def deliver(self, invite, raw_token):  # type: ignore[no-untyped-def]
            raise AssertionError("expired invite must not be delivered")

    monkeypatch.setattr(
        "app.outbox.workers.get_invite_token_sink", lambda: _MustNotCallSink()
    )

    async def _run() -> None:
        raw_token = "expired-token"
        encrypted = OutboxPayloadCrypto.from_settings().encrypt_token(raw_token)
        invite_id = UUID("00000000-0000-0000-0000-000000000181")

        async with migrated_session_factory() as session:
            session.add(
                Invite(
                    id=invite_id,
                    email="expired-worker@example.com",
                    organisation_id=UUID("00000000-0000-0000-0000-000000000001"),
                    role=MembershipRole.MEMBER,
                    status=InviteStatus.PENDING,
                    token_hash=sha256(raw_token.encode("utf-8")).hexdigest(),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite_id,
                payload_json={
                    "invite_id": str(invite_id),
                    "email": "expired-worker@example.com",
                    "encrypted_raw_token": encrypted,
                },
                status=OutboxStatus.PROCESSING.value,
                max_attempts=1,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        await _process_outbox_event(event_id)

        async with migrated_session_factory() as session:
            saved_event = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved_event is not None
            assert saved_event.status == OutboxStatus.PROCESSED.value
            assert saved_event.last_error is None
            assert "email" not in saved_event.payload_json
            assert "encrypted_raw_token" not in saved_event.payload_json
            assert saved_event.payload_json["sensitive_payload_scrubbed"] is True

            result = await session.execute(select(Invite).where(Invite.id == invite_id))
            saved_invite = result.scalar_one()
            assert saved_invite.status == InviteStatus.EXPIRED

    run_async(_run())


def test_worker_processes_disabled_delivery_without_token_decryption(
    migrated_session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )
    monkeypatch.setenv("APP__ENVIRONMENT", "dev")
    monkeypatch.setenv("OUTBOX__INVITE_DELIVERY_ENABLED", "false")
    monkeypatch.delenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", raising=False)
    reset_settings_cache()

    class _MustNotUseCrypto:
        @classmethod
        def from_settings(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("disabled delivery must not decrypt invite tokens")

    class _MustNotCallSink:
        async def deliver(self, invite, raw_token):  # type: ignore[no-untyped-def]
            raise AssertionError("disabled delivery must not call the sink")

    monkeypatch.setattr("app.outbox.workers.OutboxPayloadCrypto", _MustNotUseCrypto)
    monkeypatch.setattr(
        "app.outbox.workers.get_invite_token_sink", lambda: _MustNotCallSink()
    )

    async def _run() -> None:
        invite_id = UUID("00000000-0000-0000-0000-000000000182")

        async with migrated_session_factory() as session:
            session.add(
                Invite(
                    id=invite_id,
                    email="disabled-worker@example.com",
                    organisation_id=UUID("00000000-0000-0000-0000-000000000001"),
                    role=MembershipRole.MEMBER,
                    status=InviteStatus.PENDING,
                    token_hash=sha256(b"not-used-when-disabled").hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite_id,
                payload_json={
                    "invite_id": str(invite_id),
                    "email": "disabled-worker@example.com",
                    "encrypted_raw_token": "stale-or-undecryptable-token",
                },
                status=OutboxStatus.PROCESSING.value,
                max_attempts=1,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        await _process_outbox_event(event_id)

        async with migrated_session_factory() as session:
            saved_event = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved_event is not None
            assert saved_event.status == OutboxStatus.PROCESSED.value
            assert saved_event.last_error is None
            assert "email" not in saved_event.payload_json
            assert "encrypted_raw_token" not in saved_event.payload_json
            assert saved_event.payload_json["sensitive_payload_scrubbed"] is True

            result = await session.execute(select(Invite).where(Invite.id == invite_id))
            saved_invite = result.scalar_one()
            assert saved_invite.status == InviteStatus.PENDING

    run_async(_run())
