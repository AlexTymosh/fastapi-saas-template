from __future__ import annotations

from hashlib import sha256
from uuid import UUID

import dramatiq
from sqlalchemy import select

from app.core.db import get_session_factory
from app.core.logging import get_logger
from app.core.tasks import configure_broker
from app.invites.models.invite import Invite, InviteStatus
from app.invites.services.delivery import get_invite_token_sink
from app.outbox.models.outbox_event import OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository

log = get_logger(__name__)
configure_broker(require_redis=True)


async def _load_event_delivery_context(
    event_id: str,
) -> tuple[dict[str, object], Invite | None, str] | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.get_by_id(UUID(event_id))
            if event is None or event.status != OutboxStatus.PROCESSING.value:
                return None
            return (
                event.payload_json,
                await _load_invite(session, event.payload_json),
                event.event_type,
            )


async def _load_invite(session, payload: dict[str, object]) -> Invite | None:
    invite_id = UUID(str(payload["invite_id"]))
    return (
        await session.execute(select(Invite).where(Invite.id == invite_id))
    ).scalar_one_or_none()


async def _mark_processed(event_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.get_by_id(UUID(event_id))
            if event is None:
                return
            await repository.mark_processed(event=event)


async def _mark_failed_attempt(event_id: str, error: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.get_by_id(UUID(event_id))
            if event is None or event.status != OutboxStatus.PROCESSING.value:
                return
            await repository.mark_failed_attempt(event=event, error=error)


@dramatiq.actor(max_retries=0)
async def process_outbox_event(event_id: str) -> None:
    context = await _load_event_delivery_context(event_id)
    if context is None:
        return
    payload, invite, event_type = context
    if event_type not in {
        OutboxEventType.INVITE_CREATED.value,
        OutboxEventType.INVITE_RESEND.value,
    }:
        await _mark_processed(event_id)
        return
    if invite is None:
        await _mark_failed_attempt(event_id, "invite_not_found")
        return
    if invite.status != InviteStatus.PENDING:
        await _mark_processed(event_id)
        return

    raw_token = str(payload["raw_token"])
    if sha256(raw_token.encode("utf-8")).hexdigest() != invite.token_hash:
        await _mark_failed_attempt(event_id, "token_hash_mismatch")
        return

    try:
        sink = get_invite_token_sink()
        await sink.deliver(invite=invite, raw_token=raw_token)
    except Exception as exc:
        await _mark_failed_attempt(event_id, f"delivery_failed:{type(exc).__name__}")
        log.warning("outbox_delivery_failed", event_id=event_id)
        return

    await _mark_processed(event_id)
