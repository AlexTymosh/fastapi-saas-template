from __future__ import annotations

from uuid import UUID

import dramatiq

from app.core.db.session import get_session_factory
from app.core.logging import get_logger
from app.core.tasks.broker import configure_broker
from app.invites.models.invite import InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.invites.services.delivery import get_invite_token_sink
from app.outbox.models.outbox_event import OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository

log = get_logger(__name__)


configure_broker()


@dramatiq.actor(max_retries=10)
async def process_outbox_event(event_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = OutboxEventRepository(session)
        async with session.begin():
            event = await repository.get_by_id(UUID(event_id))
            if event is None or event.status == OutboxStatus.PROCESSED.value:
                return
            await repository.mark_processing(event=event)
        try:
            async with session.begin():
                event = await repository.get_by_id(UUID(event_id))
                if event is None or event.status == OutboxStatus.PROCESSED.value:
                    return
                await _process_event_payload(session=session, event=event)
                await repository.mark_processed(event=event)
        except Exception as exc:
            async with session.begin():
                event = await repository.get_by_id(UUID(event_id))
                if event is not None:
                    await repository.mark_failed_attempt(
                        event=event,
                        error=f"delivery_failed:{type(exc).__name__}",
                    )
            log.warning("outbox_delivery_failed", event_id=event_id)
            raise


async def _process_event_payload(*, session, event) -> None:
    if event.event_type not in {
        OutboxEventType.INVITE_CREATED.value,
        OutboxEventType.INVITE_RESEND.value,
    }:
        return
    payload = event.payload_json
    invite_id = UUID(str(payload["invite_id"]))
    raw_token = str(payload["raw_token"])
    invite = await InviteRepository(session).get_by_id(invite_id=invite_id)
    if invite is None:
        return
    if invite.status != InviteStatus.PENDING:
        return
    if InviteServiceTokenHash.token_hash(raw_token) != invite.token_hash:
        raise ValueError("invite token hash mismatch")
    sink = get_invite_token_sink()
    await sink.deliver(invite=invite, raw_token=raw_token)


@dramatiq.actor(max_retries=0)
async def enqueue_pending_outbox_events(limit: int = 100) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            pending = await OutboxEventRepository(session).list_pending_due(limit=limit)
    for event in pending:
        process_outbox_event.send(str(event.id))


class InviteServiceTokenHash:
    @staticmethod
    def token_hash(token: str) -> str:
        from hashlib import sha256

        return sha256(token.encode("utf-8")).hexdigest()
