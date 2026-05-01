from __future__ import annotations

from uuid import UUID

import dramatiq

from app.core.db.session import SessionLocal
from app.core.logging import get_logger
from app.core.tasks import broker
from app.invites.models.invite import Invite
from app.invites.services.delivery import get_invite_token_sink
from app.outbox.models.outbox_event import OutboxEventStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository

_ = broker
log = get_logger(__name__)

INVITE_CREATED_EVENT = "invite.created"
INVITE_RESEND_EVENT = "invite.resent"


@dramatiq.actor(max_retries=10)
def process_outbox_event(event_id: str) -> None:
    import asyncio

    asyncio.run(_process_outbox_event(UUID(event_id)))


async def _process_outbox_event(event_id: UUID) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            repo = OutboxEventRepository(session)
            event = await repo.get_by_id(event_id)
            if event is None or event.status == OutboxEventStatus.PROCESSED.value:
                return
            await repo.mark_processing(event)

            try:
                payload = event.payload_json
                if event.event_type in {INVITE_CREATED_EVENT, INVITE_RESEND_EVENT}:
                    invite = Invite(
                        id=UUID(str(payload["invite_id"])),
                        email=str(payload["email"]),
                        organisation_id=UUID(str(payload["organisation_id"])),
                        role=payload.get("role", "member"),
                        token_hash="",
                    )
                    sink = get_invite_token_sink()
                    await sink.deliver(
                        invite=invite, raw_token=str(payload["raw_token"])
                    )
                await repo.mark_processed(event)
            except Exception as exc:
                safe_error = f"delivery_failed:{type(exc).__name__}"
                await repo.mark_retry(event, error_message=safe_error)
                log.warning(
                    "outbox_delivery_failed",
                    event_id=str(event_id),
                    event_type=event.event_type,
                    error_type=type(exc).__name__,
                )
                raise
