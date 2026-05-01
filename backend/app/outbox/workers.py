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
configure_broker()


def _safe_error_code(exc: Exception) -> str:
    return f"delivery_failed:{type(exc).__name__}"


async def _process_outbox_event(event_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = OutboxEventRepository(session)
        event = await repository.get_by_id(UUID(event_id))
        if event is None or event.status == OutboxStatus.PROCESSED.value:
            return

        try:
            async with session.begin():
                await repository.mark_processing(event=event)
                if event.event_type in {
                    OutboxEventType.INVITE_CREATED.value,
                    OutboxEventType.INVITE_RESEND.value,
                }:
                    payload = event.payload_json
                    invite = (
                        await session.execute(
                            select(Invite).where(
                                Invite.id == UUID(str(payload["invite_id"]))
                            )
                        )
                    ).scalar_one_or_none()
                    if invite is None:
                        await repository.mark_failed_attempt(
                            event=event,
                            error="invite_not_found",
                        )
                        return
                    if invite.status != InviteStatus.PENDING:
                        await repository.mark_processed(event=event)
                        return
                    raw_token = str(payload["raw_token"])
                    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
                    if token_hash != invite.token_hash:
                        await repository.mark_failed_attempt(
                            event=event,
                            error="token_hash_mismatch",
                        )
                        return
                    sink = get_invite_token_sink()
                    await sink.deliver(invite=invite, raw_token=raw_token)
                await repository.mark_processed(event=event)
        except Exception as exc:
            async with session.begin():
                event = await repository.get_by_id(UUID(event_id))
                if event is None or event.status == OutboxStatus.PROCESSED.value:
                    return
                await repository.mark_failed_attempt(
                    event=event,
                    error=_safe_error_code(exc),
                )
            log.warning("outbox_delivery_failed", event_id=event_id)


@dramatiq.actor(max_retries=0)
async def process_outbox_event(event_id: str) -> None:
    await _process_outbox_event(event_id)


@dramatiq.actor(max_retries=0)
async def enqueue_pending_outbox_events(limit: int = 100) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = OutboxEventRepository(session)
        events = await repository.list_pending_due_events(limit=limit)

    for event in events:
        process_outbox_event.send(str(event.id))
