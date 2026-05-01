from __future__ import annotations

from uuid import UUID

import dramatiq

from app.core.db.session import get_session_factory
from app.core.logging import get_logger
from app.core.tasks import broker
from app.invites.models.invite import Invite
from app.invites.services.delivery import get_invite_token_sink
from app.outbox.models.outbox_event import OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository

log = get_logger(__name__)


@dramatiq.actor(max_retries=10)
async def process_outbox_event(event_id: str) -> None:
    _ = broker
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.get_by_id(UUID(event_id))
            if event is None or event.status == OutboxStatus.PROCESSED.value:
                return
            await repository.mark_processing(event=event)
            try:
                if event.event_type in {
                    OutboxEventType.INVITE_CREATED.value,
                    OutboxEventType.INVITE_RESEND.value,
                }:
                    payload = event.payload_json
                    invite = Invite(
                        id=UUID(payload["invite_id"]),
                        email=str(payload["email"]),
                        organisation_id=UUID(payload["organisation_id"]),
                        role=payload["role"],
                        token_hash="",
                    )
                    sink = get_invite_token_sink()
                    await sink.deliver(
                        invite=invite, raw_token=str(payload["raw_token"])
                    )
                await repository.mark_processed(event=event)
            except Exception as exc:
                await repository.mark_failed_attempt(
                    event=event,
                    error=f"delivery_failed:{type(exc).__name__}",
                )
                log.warning("outbox_delivery_failed", event_id=event_id)
                raise
